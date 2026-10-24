"""Fictional roadside-assistance platform (DEMO).

Simulates the kind of third-party web platform where insurers publish towing and
roadside-assistance jobs for tow companies. Jobs appear over time; the first
company to accept one (assigning a resource/truck) gets it, and jobs that nobody
accepts in time are taken by "another company".

All names, insurers and data are invented. It exists only so the RPA bot has a
stable, self-hosted target to automate.
"""

from __future__ import annotations

import os
import random
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

PORTAL_USER = os.getenv("PORTAL_USER", "demo")
PORTAL_PASSWORD = os.getenv("PORTAL_PASSWORD", "demo1234")
SESSION_SECRET = os.getenv("PORTAL_SESSION_SECRET") or secrets.token_hex(32)
NEW_SERVICE_EVERY = float(os.getenv("PORTAL_NEW_SERVICE_EVERY", "7"))
SERVICE_TTL = float(os.getenv("PORTAL_SERVICE_TTL", "45"))
MAX_PENDING = int(os.getenv("PORTAL_MAX_PENDING", "12"))
DEMO_PUBLIC = os.getenv("DEMO_PUBLIC", "false").lower() in ("1", "true", "yes")
PANEL_PUBLIC_URL = os.getenv("PANEL_PUBLIC_URL", "")

SERVICE_TYPES = {  # type: (weight, base price €)
    "Arrastre": (5, 70.0),
    "Batería": (2, 45.0),
    "Pinchazo": (2, 40.0),
    "Combustible": (1, 40.0),
    "Apertura": (1, 50.0),
}
VEHICLES = {  # category: (weight, example models)
    "Turismo": (6, ["Turismo compacto", "Berlina", "Utilitario", "Monovolumen"]),
    "Furgoneta": (2, ["Furgoneta mediana", "Furgoneta grande"]),
    "4x4": (1, ["Todoterreno", "SUV"]),
    "Moto": (1, ["Motocicleta", "Scooter"]),
}
# IDs are tenths of a second since this date, so they never repeat between platform restarts
# (the bot keeps its history in SQLite and must not confuse a new service with an old one).
ID_EPOCH = 1767225600  # 2026-01-01 UTC
ZONES = ["Centro", "Norte", "Sur", "Este", "Oeste"]
STREETS = ["Av. de la Constitución", "Calle Mayor", "Ctra. Nacional km", "Polígono Industrial, nave",
           "Ronda Sur", "Calle Real", "Autovía, salida", "Plaza de España"]
INSURERS = ["Aseguradora Alfa", "Seguros Beta", "Mutua Gamma", "Delta Seguros"]
PLATE_LETTERS = "BCDFGHJKLMNPRSTVWXYZ"


@dataclass
class Service:
    id: int
    case_number: str
    insurer: str
    service_type: str
    vehicle_type: str
    vehicle_model: str
    plate: str
    zone: str
    address: str
    destination: str
    distance_km: float
    amount_eur: float
    published_at: float
    expires_at: float
    status: str = "pendiente"  # pendiente | aceptado | perdido
    resource: str | None = None
    closed_at: float | None = None

    @property
    def seconds_left(self) -> int:
        return max(0, int(self.expires_at - time.time()))


class ServiceStore:
    def __init__(self, seed: int | None = None) -> None:
        self._services: dict[int, Service] = {}
        self._next_id = int((time.time() - ID_EPOCH) * 10)
        self._last_generated = time.time()
        self._lock = threading.Lock()
        self._rng = random.Random(seed)
        for _ in range(4):
            self._create()

    def _weighted(self, table: dict) -> str:
        keys = list(table)
        return self._rng.choices(keys, weights=[table[k][0] for k in keys])[0]

    def _create(self, published_at: float | None = None) -> Service:
        rng = self._rng
        stype = self._weighted(SERVICE_TYPES)
        vtype = self._weighted(VEHICLES)
        if stype == "Arrastre" and rng.random() < 0.3:
            vtype = "Furgoneta"
        zone = rng.choice(ZONES)
        km = round(rng.uniform(3, 65), 1)
        base = SERVICE_TYPES[stype][1]
        amount = round(base + km * (1.6 if stype == "Arrastre" else 0.9), 2)
        now = published_at or time.time()
        service_id = max(self._next_id, int((now - ID_EPOCH) * 10))
        service = Service(
            id=service_id,
            case_number=f"EXP-{time.strftime('%y')}-{service_id % 1_000_000:06d}",
            insurer=rng.choice(INSURERS),
            service_type=stype,
            vehicle_type=vtype,
            vehicle_model=rng.choice(VEHICLES[vtype][1]),
            plate=f"{rng.randint(1000, 9999)} {''.join(rng.choices(PLATE_LETTERS, k=3))}",
            zone=zone,
            address=f"{rng.choice(STREETS)} {rng.randint(1, 120)} ({zone})",
            destination=f"Taller concertado ({rng.choice(ZONES)})" if stype == "Arrastre" else "In situ",
            distance_km=km,
            amount_eur=amount,
            published_at=now,
            expires_at=now + SERVICE_TTL,
        )
        self._services[service.id] = service
        self._next_id = service_id + 1
        return service

    def _tick(self) -> None:
        now = time.time()
        # Publish each service at its scheduled time even if nobody was looking,
        # so response times measured by the bot are real.
        while self._last_generated + NEW_SERVICE_EVERY <= now:
            self._last_generated += NEW_SERVICE_EVERY
            if self._last_generated + SERVICE_TTL <= now:
                continue  # would already have expired unseen
            if sum(s.status == "pendiente" for s in self._services.values()) < MAX_PENDING:
                self._create(published_at=self._last_generated)
        for s in self._services.values():
            if s.status == "pendiente" and s.expires_at <= now:
                s.status, s.resource, s.closed_at = "perdido", "Otra empresa", s.expires_at

    def pending(self) -> list[Service]:
        with self._lock:
            self._tick()
            return sorted((s for s in self._services.values() if s.status == "pendiente"), key=lambda s: s.id)

    def closed(self, limit: int = 12) -> list[Service]:
        with self._lock:
            done = [s for s in self._services.values() if s.status != "pendiente"]
            return sorted(done, key=lambda s: s.closed_at or 0, reverse=True)[:limit]

    def accept(self, service_id: int, resource: str) -> Service:
        with self._lock:
            self._tick()
            s = self._services.get(service_id)
            if s is None or s.status != "pendiente":
                raise KeyError(service_id)
            s.status, s.resource, s.closed_at = "aceptado", resource, time.time()
            return s


app = FastAPI(title="Plataforma de Asistencia (DEMO)")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals.update(
    panel_url=PANEL_PUBLIC_URL,
    demo_credentials=(PORTAL_USER, PORTAL_PASSWORD) if DEMO_PUBLIC else None,
)
store = ServiceStore()


def _logged_in(request: Request) -> bool:
    return request.session.get("user") == PORTAL_USER


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index(request: Request) -> RedirectResponse:
    return RedirectResponse("/servicios" if _logged_in(request) else "/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ok = secrets.compare_digest(username, PORTAL_USER) & secrets.compare_digest(password, PORTAL_PASSWORD)
    if not ok:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Usuario o contraseña incorrectos"}, status_code=401
        )
    request.session["user"] = username
    return RedirectResponse("/servicios", status_code=303)


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/servicios", response_class=HTMLResponse)
def services(request: Request):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "servicios.html",
        {"pending": store.pending(), "closed": store.closed(), "company": PORTAL_USER},
    )


@app.post("/servicios/{service_id}/aceptar")
def accept(request: Request, service_id: int, recurso: str = Form(...)):
    if not _logged_in(request):
        raise HTTPException(status_code=401, detail="No autenticado")
    resource = recurso.strip()
    if not resource:
        raise HTTPException(status_code=422, detail="Indica el recurso asignado")
    try:
        store.accept(service_id, resource[:40])
    except KeyError:
        raise HTTPException(status_code=409, detail="El servicio ya no está disponible")
    return RedirectResponse("/servicios", status_code=303)
