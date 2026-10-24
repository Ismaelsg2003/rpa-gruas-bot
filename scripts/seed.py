"""Load the demo fleet and example rules (idempotent).

    python -m scripts.seed           # load fleet and rules if missing
    python -m scripts.seed --reset   # also wipe history (services, jobs, events) for a clean demo
"""

from __future__ import annotations

import argparse

from bot.config import get_settings
from bot.db import Database
from bot.demo import seed, wipe_history
from bot.models import UNIT_TYPE_LABELS


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga la flota y las reglas de ejemplo")
    parser.add_argument("--reset", action="store_true", help="Borra el historial para empezar la demo de cero")
    args = parser.parse_args()

    db = Database(get_settings().db_path)
    if args.reset:
        wipe_history(db)
        db.set_setting("bot_paused", "0")
        print("Historial borrado")
    seed(db)

    print("Flota:")
    for u in db.list_units():
        print(f"  {u.code}  {u.driver:<8} {UNIT_TYPE_LABELS[u.unit_type]:<24} base {u.base_zone}")
    print("Reglas:")
    for r in db.list_rules():
        print(f"  [{'ON ' if r.active else 'OFF'}] {r.name}: {r.field} {r.operator.value} {r.value}")
    db.close()


if __name__ == "__main__":
    main()
