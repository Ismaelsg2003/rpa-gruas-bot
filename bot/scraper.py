"""Playwright automation of the assistance platform."""

from __future__ import annotations

import logging
from types import TracebackType

from playwright.sync_api import Browser, Locator, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from bot.models import Service

log = logging.getLogger(__name__)

SERVICES_PATH = "/servicios"


class LoginError(RuntimeError):
    pass


class PortalClient:
    """Wraps a browser session against the platform. Use as a context manager."""

    def __init__(self, base_url: str, username: str, password: str, headless: bool = True, channel: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._headless = headless
        self._channel = channel or None
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    # ---- lifecycle -------------------------------------------------------
    def __enter__(self) -> PortalClient:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless, channel=self._channel)
        self._page = self._browser.new_page(viewport={"width": 1400, "height": 900})
        self._page.set_default_timeout(15_000)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # On Ctrl+C the Playwright driver may already be gone; closing must not crash.
        for close in (self._browser.close if self._browser else None, self._pw.stop if self._pw else None):
            if close is None:
                continue
            try:
                close()
            except Exception:  # noqa: BLE001
                log.debug("El navegador ya estaba cerrado")

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("PortalClient no iniciado: úsalo con 'with'")
        return self._page

    # ---- actions ---------------------------------------------------------
    def login(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}/login")
        page.fill("#username", self._username)
        page.fill("#password", self._password)
        page.click("[data-testid=login-submit]")
        page.wait_for_load_state("domcontentloaded")
        if SERVICES_PATH not in page.url:
            raise LoginError("Login rechazado: revisa PORTAL_USER y PORTAL_PASSWORD")
        log.info("Sesión iniciada en %s", self.base_url)

    def _open_services(self) -> None:
        page = self.page
        page.goto(f"{self.base_url}{SERVICES_PATH}")
        if "/login" in page.url:
            log.info("Sesión caducada, volviendo a entrar")
            self.login()
        page.wait_for_selector("[data-testid=services-table]")

    @staticmethod
    def _parse_row(row: Locator) -> Service:
        def field(name: str) -> str:
            return row.locator(f"[data-field={name}]").inner_text().strip()

        return Service(
            id=int(row.get_attribute("data-service-id") or ""),
            case_number=field("case_number"),
            insurer=field("insurer"),
            service_type=field("service_type"),
            vehicle_type=field("vehicle_type"),
            vehicle_model=field("vehicle_model"),
            plate=field("plate"),
            zone=field("zone"),
            address=field("address"),
            destination=field("destination"),
            distance_km=float(field("distance_km")),
            amount_eur=float(field("amount_eur")),
            published_at=float(row.get_attribute("data-published-at") or 0),
        )

    def fetch_pending_services(self) -> list[Service]:
        self._open_services()
        services: list[Service] = []
        for row in self.page.locator("[data-testid=service-row]").all():
            try:
                services.append(self._parse_row(row))
            except (ValueError, PlaywrightTimeout):
                log.warning("Fila con formato inesperado, se ignora")
        return services

    def accept_service(self, service_id: int, resource: str) -> bool:
        """Types the resource and clicks 'Aceptar'. Returns False if the platform refused it."""
        self._open_services()
        button = self.page.locator(f"[data-testid=accept-{service_id}]")
        if button.count() == 0:
            log.info("El servicio %s ya no está en la plataforma", service_id)
            return False
        self.page.fill(f"[data-testid=resource-{service_id}]", resource)
        try:
            with self.page.expect_response(lambda r: f"/servicios/{service_id}/aceptar" in r.url) as info:
                button.click()
            response = info.value
        except PlaywrightTimeout:
            log.error("Timeout aceptando el servicio %s", service_id)
            return False
        ok = response.status in (200, 303)
        if not ok:
            log.warning("La plataforma rechazó el servicio %s (HTTP %s)", service_id, response.status)
        return ok
