"""Control panel for the tow company manager.

Reads the same SQLite database the bot writes to and lets the manager see the
fleet and the bot's decisions live, change the acceptance rules, take a truck
out of service or pause the bot, all without touching code.

Run with:  uvicorn dashboard.app:app --port 8001
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from bot.config import get_settings
from bot.db import Database
from bot.demo import seconds_until_reset
from bot.fleet import DEFAULT_MAX_QUEUE_WAIT_S, job_progress
from bot.models import RULE_FIELDS, UNIT_TYPE_LABELS, Operator
from bot.rules import RuleError

STATIC = Path(__file__).parent / "static"
BOT_OFFLINE_AFTER_S = 20
MAX_RULES_PUBLIC_DEMO = 12

OPERATOR_LABELS = {
    Operator.IN: "es uno de",
    Operator.NOT_IN: "no es ninguno de",
    Operator.EQ: "es",
    Operator.NE: "no es",
    Operator.GTE: "es como mínimo",
    Operator.LTE: "es como máximo",
    Operator.GT: "es mayor que",
    Operator.LT: "es menor que",
}

app = FastAPI(title="Centro de control · Grúas (demo)")


def get_db() -> Iterator[Database]:
    db = Database(get_settings().db_path)
    try:
        yield db
    finally:
        db.close()


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    field: str
    operator: Operator
    value: str = Field(min_length=1, max_length=200)


class RulePatch(BaseModel):
    value: str | None = Field(default=None, max_length=200)
    active: bool | None = None


class Toggle(BaseModel):
    active: bool


class Pause(BaseModel):
    paused: bool


class QueueWait(BaseModel):
    seconds: int = Field(ge=0, le=3600)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def state(db: Database = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    now = time.time()
    heartbeat = float(db.get_setting("bot_heartbeat", "0") or 0)
    jobs = [j for j in db.recent_jobs(now - 3600) if j.finishes_at > now]
    services = db.services_by_ids({j.service_id for j in jobs})
    jobs_today = db.count_jobs_today()

    def job_view(job: Any) -> dict[str, Any]:
        p = job_progress(job, now)
        s = services.get(job.service_id, {})
        return {
            "case_number": s.get("case_number"),
            "service_type": s.get("service_type"),
            "vehicle_type": s.get("vehicle_type"),
            "zone": s.get("zone"),
            "address": s.get("address"),
            "state": p.state,
            "label": p.label,
            "progress": round(p.progress, 3),
            "travel_share": round(job.travel_seconds / (job.travel_seconds + job.work_seconds), 3),
            "seconds_left": p.seconds_left,
            "starts_in": p.starts_in,
        }

    units = []
    for u in db.list_units():
        mine = sorted((j for j in jobs if j.unit_id == u.id), key=lambda j: j.starts_at)
        current = next((j for j in mine if j.starts_at <= now), None)
        queue = [j for j in mine if j.starts_at > now]
        job_info = job_view(current) if current else None
        queue_info = [job_view(j) for j in queue]
        units.append({
            "id": u.id,
            "code": u.code,
            "driver": u.driver,
            "type": u.unit_type.value,
            "type_label": UNIT_TYPE_LABELS[u.unit_type],
            "base_zone": u.base_zone,
            "active": u.active,
            "jobs_today": jobs_today.get(u.id, 0),
            "job": job_info,
            "queue": queue_info,
            "free_in": int(round(max(j.finishes_at for j in mine) - now)) if mine else 0,
        })

    return {
        "now": now,
        "bot": {"online": now - heartbeat < BOT_OFFLINE_AFTER_S, "paused": db.is_paused()},
        "max_queue_wait": db.max_queue_wait(DEFAULT_MAX_QUEUE_WAIT_S),
        "demo": {
            "public": settings.demo_public,
            "reset_minutes": settings.demo_reset_minutes,
            "reset_in": int(seconds_until_reset(db, settings.demo_reset_minutes, now)) if settings.demo_public else None,
            "platform_url": settings.platform_public_url,
        },
        "stats": db.stats_today(),
        "units": units,
        "events": db.recent_events(40),
        "services": db.services_today(60),
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "field": r.field,
                "field_label": RULE_FIELDS[r.field],
                "operator": r.operator.value,
                "operator_label": OPERATOR_LABELS[r.operator],
                "value": r.value,
                "active": r.active,
            }
            for r in db.list_rules()
        ],
        "fields": RULE_FIELDS,
        "operators": {op.value: label for op, label in OPERATOR_LABELS.items()},
    }


@app.post("/api/rules", status_code=201)
def create_rule(body: RuleIn, db: Database = Depends(get_db)) -> dict[str, int]:
    if get_settings().demo_public and len(db.list_rules()) >= MAX_RULES_PUBLIC_DEMO:
        raise HTTPException(400, f"En la demo pública hay un máximo de {MAX_RULES_PUBLIC_DEMO} reglas. Elimina alguna antes.")
    try:
        rule_id = db.add_rule(body.name, body.field, body.operator, body.value)
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Ya existe una regla con ese nombre")
    except (RuleError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    db.add_event("config", f"Regla creada: {body.name}")
    return {"id": rule_id}


@app.patch("/api/rules/{rule_id}")
def update_rule(rule_id: int, body: RulePatch, db: Database = Depends(get_db)) -> dict[str, bool]:
    rule = db.get_rule(rule_id)
    if rule is None:
        raise HTTPException(404, "La regla no existe")
    try:
        db.update_rule(rule_id, value=body.value, active=body.active)
    except RuleError as exc:
        raise HTTPException(400, str(exc))
    if body.active is not None and body.active != rule.active:
        db.add_event("config", f"Regla {'activada' if body.active else 'desactivada'}: {rule.name}")
    if body.value is not None and body.value.strip() != rule.value:
        db.add_event("config", f"Regla cambiada: {rule.name} → {body.value.strip()}")
    return {"ok": True}


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int, db: Database = Depends(get_db)) -> dict[str, bool]:
    rule = db.get_rule(rule_id)
    if rule is None:
        raise HTTPException(404, "La regla no existe")
    db.delete_rule(rule_id)
    db.add_event("config", f"Regla eliminada: {rule.name}")
    return {"ok": True}


@app.patch("/api/units/{unit_id}")
def toggle_unit(unit_id: int, body: Toggle, db: Database = Depends(get_db)) -> dict[str, bool]:
    unit = next((u for u in db.list_units() if u.id == unit_id), None)
    if unit is None:
        raise HTTPException(404, "La grúa no existe")
    db.set_unit_active(unit_id, body.active)
    db.add_event("config", f"{unit.code} ({unit.driver}) {'vuelve al servicio' if body.active else 'fuera de servicio'}",
                 unit_id=unit_id)
    return {"ok": True}


@app.post("/api/bot/pause")
def pause_bot(body: Pause, db: Database = Depends(get_db)) -> dict[str, bool]:
    db.set_setting("bot_paused", "1" if body.paused else "0")
    return {"paused": body.paused}


@app.post("/api/settings/max-queue-wait")
def set_max_queue_wait(body: QueueWait, db: Database = Depends(get_db)) -> dict[str, int]:
    db.set_setting("max_queue_wait_s", str(body.seconds))
    db.add_event("config", f"Espera máxima en cola: {body.seconds} s")
    return {"seconds": body.seconds}
