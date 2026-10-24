"""RPA bot: watches the assistance platform, accepts services and assigns trucks.

Run with:  python -m bot.main          (loop until Ctrl+C)
           python -m bot.main --once   (single cycle, useful for testing)
"""

from __future__ import annotations

import argparse
import logging
import signal
import time

from bot.config import get_settings
from bot.db import Database
from bot.demo import reset_demo, seconds_until_reset
from bot.fleet import DEFAULT_MAX_QUEUE_WAIT_S, choose_unit, plan_job
from bot.models import Service
from bot.notifier import Notifier
from bot.rules import RuleError, decide
from bot.scraper import LoginError, PortalClient

log = logging.getLogger("bot")
_stop = False


def _handle_stop(signum: int, _frame: object) -> None:
    global _stop
    log.info("Señal %s recibida, terminando tras el ciclo actual", signum)
    _stop = True


def _short(s: Service) -> str:
    return f"{s.case_number} · {s.service_type} {s.vehicle_type} en {s.zone} ({s.amount_eur:.2f} €)"


def run_cycle(client: PortalClient, db: Database, notifier: Notifier) -> int:
    """One polling cycle. Returns how many services were accepted."""
    rules = db.list_rules(only_active=True)
    units = db.list_units()
    pending = client.fetch_pending_services()
    pending_ids = {s.id for s in pending}

    # Services we were waiting on that disappeared: another company got them.
    for service_id in db.waiting_service_ids() - pending_ids:
        db.set_service_status(service_id, "lost")
        db.add_event("lost", "Perdido: ninguna grúa adecuada podía atenderlo a tiempo", service_id)

    max_wait = db.max_queue_wait(DEFAULT_MAX_QUEUE_WAIT_S)
    accepted = 0
    for service in pending:
        status = db.service_status(service.id)
        if status in ("accepted", "rejected", "lost", "failed"):
            continue
        if status is None:
            db.record_service(service)

        try:
            decision = decide(service, rules)
        except RuleError as exc:
            log.error("Regla mal definida: %s", exc)
            db.add_event("error", f"Regla mal definida: {exc}")
            return accepted

        if not decision.accepted:
            db.set_service_status(service.id, "rejected")
            db.add_event("rejected", decision.reason, service.id)
            log.info("Descartado %s → %s", _short(service), decision.reason)
            continue

        now = time.time()
        assignment = choose_unit(service, units, db.recent_jobs(now - 3600), now, max_wait)
        if assignment is None:
            if status != "waiting":
                db.set_service_status(service.id, "waiting")
                db.add_event(
                    "waiting",
                    f"Cumple las reglas, pero todas las grúas adecuadas tardarían más de {max_wait:.0f} s en salir;"
                    " reintentando mientras siga publicado",
                    service.id,
                )
                log.info("Flota saturada para %s, reintentando mientras siga publicado", _short(service))
            continue

        unit = assignment.unit
        if not client.accept_service(service.id, unit.code):
            db.set_service_status(service.id, "failed")
            db.add_event("failed", "La plataforma no permitió aceptarlo (ya no estaba disponible)", service.id)
            continue

        accepted_at = time.time()
        response = max(0.0, accepted_at - service.published_at)
        db.add_job(plan_job(service, unit, accepted_at, start_at=assignment.start_at))
        db.set_service_status(service.id, "accepted", response_seconds=response)
        seconds = f"{response:.1f}".replace(".", ",")
        if assignment.queued:
            wait = assignment.start_at - accepted_at
            msg = f"Aceptado en {seconds} s y puesto en cola de {unit.code} ({unit.driver}): sale en {wait:.0f} s"
        else:
            wait = 0.0
            msg = f"Aceptado en {seconds} s y asignado a {unit.code} ({unit.driver}), que sale ya"
        db.add_event("accepted", msg, service.id, unit.id)
        log.info("ACEPTADO %s → %s (%s) en %.1f s%s", _short(service), unit.code, unit.driver, response,
                 f", en cola {wait:.0f} s" if wait else "")
        notifier.service_assigned(service, unit, response, wait)
        accepted += 1
    return accepted


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot RPA de aceptación y asignación de servicios de grúa")
    parser.add_argument("--once", action="store_true", help="Ejecuta un solo ciclo y termina")
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    db = Database(settings.db_path)
    token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else None
    notifier = Notifier(token, settings.telegram_chat_id)

    if not db.list_units():
        log.warning("No hay grúas en la flota: ejecuta 'python -m scripts.seed' primero")

    with PortalClient(
        settings.portal_url,
        settings.portal_user,
        settings.portal_password.get_secret_value(),
        headless=settings.headless,
        channel=settings.browser_channel,
    ) as client:
        try:
            client.login()
        except LoginError as exc:
            log.error("%s", exc)
            db.add_event("error", str(exc))
            db.close()
            raise SystemExit(1) from None

        db.add_event("info", "Bot iniciado y conectado a la plataforma")
        was_paused = False
        while not _stop:
            if settings.demo_public and seconds_until_reset(db, settings.demo_reset_minutes) == 0:
                reset_demo(db)
                db.add_event("info", f"Demo pública restablecida: flota, reglas e historial iniciales "
                                     f"(se repite cada {settings.demo_reset_minutes} min)")
                log.info("Demo pública restablecida")
                was_paused = False
            db.set_setting("bot_heartbeat", str(time.time()))
            paused = db.is_paused()
            if paused != was_paused:
                db.add_event("info", "Bot en pausa" if paused else "Bot reanudado")
                log.info("Bot %s", "en pausa" if paused else "reanudado")
                was_paused = paused
            if not paused:
                try:
                    run_cycle(client, db, notifier)
                except Exception:  # keep the bot alive on unexpected platform errors
                    log.exception("Error en el ciclo, se reintentará")
            if args.once:
                break
            deadline = time.time() + settings.poll_interval_seconds
            while not _stop and time.time() < deadline:
                time.sleep(0.25)

    db.add_event("info", "Bot detenido")
    log.info("Resumen de hoy: %s", db.stats_today())
    db.close()


if __name__ == "__main__":
    main()
