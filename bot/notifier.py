"""Notifications. Sends to Telegram if configured, otherwise only logs."""

from __future__ import annotations

import logging
from html import escape

import httpx

from bot.models import UNIT_TYPE_LABELS, Service, Unit

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, token: str | None, chat_id: str | None, timeout: float = 10.0) -> None:
        self.enabled = bool(token and chat_id)
        self._url = f"https://api.telegram.org/bot{token}/sendMessage" if token else ""
        self._chat_id = chat_id
        self._timeout = timeout
        if not self.enabled:
            log.warning("Telegram no configurado: los avisos solo se mostrarán en el log")

    def send(self, text: str) -> bool:
        if not self.enabled:
            log.info("[aviso] %s", text.replace("\n", " | "))
            return False
        try:
            resp = httpx.post(
                self._url,
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            # Never log the URL: it contains the bot token.
            log.error("Error enviando aviso a Telegram: %s", type(exc).__name__)
            return False

    def service_assigned(self, service: Service, unit: Unit, response_seconds: float, wait_seconds: float = 0) -> bool:
        departure = f"en cola, sale en {wait_seconds:.0f} s" if wait_seconds else "sale ya"
        text = (
            f"🚛 <b>{escape(service.case_number)} aceptado</b> en {response_seconds:.1f} s\n"
            f"{escape(service.service_type)} · {escape(service.vehicle_type)} ({escape(service.plate)})\n"
            f"📍 {escape(service.address)}\n"
            f"➡️ {escape(service.destination)} · {service.distance_km:.1f} km\n"
            f"💶 {service.amount_eur:.2f} € · {escape(service.insurer)}\n"
            f"👷 Asignado a <b>{escape(unit.code)}</b> ({UNIT_TYPE_LABELS[unit.unit_type]}) · {escape(unit.driver)}, {departure}"
        )
        return self.send(text)
