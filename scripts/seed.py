"""Load the demo fleet and example rules (idempotent).

    python -m scripts.seed           # load fleet and rules if missing
    python -m scripts.seed --reset   # also wipe history (services, jobs, events) for a clean demo
"""

from __future__ import annotations

import argparse
import sqlite3

from bot.config import get_settings
from bot.db import Database
from bot.models import UNIT_TYPE_LABELS, UnitType

# Fictional fleet.
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga la flota y las reglas de ejemplo")
    parser.add_argument("--reset", action="store_true", help="Borra el historial para empezar la demo de cero")
    args = parser.parse_args()

    db = Database(get_settings().db_path)
    if args.reset:
        with db._tx() as c:  # noqa: SLF001 - maintenance script
            c.executescript("DELETE FROM jobs; DELETE FROM events; DELETE FROM services; DELETE FROM settings;")
        print("Historial borrado")

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

    print("Flota:")
    for u in db.list_units():
        print(f"  {u.code}  {u.driver:<8} {UNIT_TYPE_LABELS[u.unit_type]:<24} base {u.base_zone}")
    print("Reglas:")
    for r in db.list_rules():
        print(f"  [{'ON ' if r.active else 'OFF'}] {r.name}: {r.field} {r.operator.value} {r.value}")
    db.close()


if __name__ == "__main__":
    main()
