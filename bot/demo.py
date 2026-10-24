"""Demo data (fictional fleet and example rules) and the public-demo reset.

When the demo runs publicly, every visitor shares the same panel, so the bot
restores the original fleet, rules and an empty history every so often.
"""

from __future__ import annotations

import sqlite3
import time

from bot.db import Database
from bot.models import UnitType

FLEET: list[tuple[str, str, UnitType, str]] = [
    ("G-01", "Antonio", UnitType.LIGHT_TOW, "Centro"),
    ("G-02", "Lucía", UnitType.LIGHT_TOW, "Norte"),
    ("G-03", "Manuel", UnitType.HEAVY_TOW, "Sur"),
    ("A-04", "Carmen", UnitType.ASSIST, "Este"),
    ("A-05", "Javier", UnitType.ASSIST, "Oeste"),
]

RULES: list[tuple[str, str, str, str]] = [
    ("Aseguradoras con convenio", "insurer", "in", "Aseguradora Alfa,Seguros Beta,Mutua Gamma"),
    ("Importe mínimo", "amount_eur", "gte", "55"),
    ("Distancia máxima", "distance_km", "lte", "50"),
    ("No hacemos aperturas", "service_type", "ne", "Apertura"),
]

LAST_RESET_KEY = "demo_last_reset"


def seed(db: Database) -> None:
    """Insert the demo fleet and rules if they are missing (idempotent)."""
    for code, driver, unit_type, zone in FLEET:
        try:
            db.add_unit(code, driver, unit_type, zone)
        except sqlite3.IntegrityError:
            pass
    for name, field, op, value in RULES:
        try:
            db.add_rule(name, field, op, value)
        except sqlite3.IntegrityError:
            pass


def wipe_history(db: Database) -> None:
    db.execute_script("DELETE FROM jobs; DELETE FROM events; DELETE FROM services;")


def reset_demo(db: Database) -> None:
    """Back to the initial state: empty history, original fleet and rules, default settings."""
    db.execute_script(
        "DELETE FROM jobs; DELETE FROM events; DELETE FROM services;"
        " DELETE FROM rules; DELETE FROM units; DELETE FROM settings;"
    )
    seed(db)
    db.set_setting(LAST_RESET_KEY, str(time.time()))


def seconds_until_reset(db: Database, every_minutes: int, now: float | None = None) -> float:
    now = time.time() if now is None else now
    last = float(db.get_setting(LAST_RESET_KEY, "0") or 0)
    return max(0.0, last + every_minutes * 60 - now)
