"""SQLite persistence shared by the bot (writer) and the control panel."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from bot.models import RULE_FIELDS, Job, Operator, Rule, Service, Unit, UnitType
from bot.rules import validate_rule

SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    field      TEXT NOT NULL,
    operator   TEXT NOT NULL,
    value      TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS units (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    code      TEXT NOT NULL UNIQUE,
    driver    TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    base_zone TEXT NOT NULL,
    active    INTEGER NOT NULL DEFAULT 1
);

-- Every service the bot has seen on the platform and what happened to it.
CREATE TABLE IF NOT EXISTS services (
    id           INTEGER PRIMARY KEY,
    case_number  TEXT NOT NULL,
    insurer      TEXT NOT NULL,
    service_type TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    vehicle_model TEXT NOT NULL,
    plate        TEXT NOT NULL,
    zone         TEXT NOT NULL,
    address      TEXT NOT NULL,
    destination  TEXT NOT NULL,
    distance_km  REAL NOT NULL,
    amount_eur   REAL NOT NULL,
    published_at REAL NOT NULL,
    first_seen   REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new'
                 CHECK (status IN ('new', 'waiting', 'accepted', 'rejected', 'lost', 'failed')),
    response_seconds REAL
);

CREATE TABLE IF NOT EXISTS jobs (
    service_id     INTEGER PRIMARY KEY REFERENCES services(id),
    unit_id        INTEGER NOT NULL REFERENCES units(id),
    assigned_at    REAL NOT NULL,
    travel_seconds REAL NOT NULL,
    work_seconds   REAL NOT NULL,
    start_at       REAL NOT NULL DEFAULT 0
);

-- Activity feed shown live in the control panel.
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    message    TEXT NOT NULL,
    service_id INTEGER,
    unit_id    INTEGER,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_services_status ON services(status);
"""


def start_of_today() -> float:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")  # bot writes while the panel reads
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Small forward-only migrations for databases created by older versions."""
        job_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(jobs)")}
        if "start_at" not in job_cols:
            with self._tx() as c:
                c.execute("ALTER TABLE jobs ADD COLUMN start_at REAL NOT NULL DEFAULT 0")

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    def execute_script(self, sql: str) -> None:
        """Run several maintenance statements atomically."""
        self._conn.executescript("BEGIN; " + sql + " COMMIT;")

    # ---- rules -----------------------------------------------------------
    @staticmethod
    def _rule(row: sqlite3.Row) -> Rule:
        return Rule(row["id"], row["name"], row["field"], Operator(row["operator"]), row["value"], bool(row["active"]))

    def add_rule(self, name: str, field: str, operator: Operator | str, value: str, active: bool = True) -> int:
        if field not in RULE_FIELDS:
            raise ValueError(f"Campo no válido: {field}")
        rule = Rule(0, name.strip(), field, Operator(operator), value.strip(), active)
        validate_rule(rule)
        if not rule.name:
            raise ValueError("La regla necesita un nombre")
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO rules (name, field, operator, value, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (rule.name, field, rule.operator.value, rule.value, int(active), time.time()),
            )
            return int(cur.lastrowid)

    def get_rule(self, rule_id: int) -> Rule | None:
        row = self._conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
        return self._rule(row) if row else None

    def list_rules(self, only_active: bool = False) -> list[Rule]:
        sql = "SELECT * FROM rules" + (" WHERE active = 1" if only_active else "") + " ORDER BY id"
        return [self._rule(r) for r in self._conn.execute(sql)]

    def update_rule(self, rule_id: int, *, value: str | None = None, active: bool | None = None) -> None:
        current = self.get_rule(rule_id)
        if current is None:
            raise KeyError(rule_id)
        new_value = current.value if value is None else value.strip()
        new_active = current.active if active is None else active
        validate_rule(Rule(current.id, current.name, current.field, current.operator, new_value, new_active))
        with self._tx() as c:
            c.execute("UPDATE rules SET value = ?, active = ? WHERE id = ?", (new_value, int(new_active), rule_id))

    def delete_rule(self, rule_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM rules WHERE id = ?", (rule_id,))

    # ---- fleet -----------------------------------------------------------
    @staticmethod
    def _unit(row: sqlite3.Row) -> Unit:
        return Unit(row["id"], row["code"], row["driver"], UnitType(row["unit_type"]), row["base_zone"],
                    bool(row["active"]))

    def add_unit(self, code: str, driver: str, unit_type: UnitType | str, base_zone: str) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO units (code, driver, unit_type, base_zone) VALUES (?, ?, ?, ?)",
                (code, driver, UnitType(unit_type).value, base_zone),
            )
            return int(cur.lastrowid)

    def list_units(self) -> list[Unit]:
        return [self._unit(r) for r in self._conn.execute("SELECT * FROM units ORDER BY code")]

    def set_unit_active(self, unit_id: int, active: bool) -> None:
        with self._tx() as c:
            c.execute("UPDATE units SET active = ? WHERE id = ?", (int(active), unit_id))

    # ---- services --------------------------------------------------------
    def service_status(self, service_id: int) -> str | None:
        row = self._conn.execute("SELECT status FROM services WHERE id = ?", (service_id,)).fetchone()
        return row["status"] if row else None

    def record_service(self, s: Service) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO services (id, case_number, insurer, service_type, vehicle_type, vehicle_model,"
                " plate, zone, address, destination, distance_km, amount_eur, published_at, first_seen)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (s.id, s.case_number, s.insurer, s.service_type, s.vehicle_type, s.vehicle_model, s.plate, s.zone,
                 s.address, s.destination, s.distance_km, s.amount_eur, s.published_at, time.time()),
            )

    def set_service_status(self, service_id: int, status: str, response_seconds: float | None = None) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE services SET status = ?, response_seconds = COALESCE(?, response_seconds) WHERE id = ?",
                (status, response_seconds, service_id),
            )

    def services_by_ids(self, ids: set[int]) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._conn.execute(f"SELECT * FROM services WHERE id IN ({marks})", tuple(ids))
        return {r["id"]: dict(r) for r in rows}

    def services_today(self, limit: int = 60) -> list[dict[str, Any]]:
        """Every service the bot saw today with its outcome, unit and latest reason."""
        rows = self._conn.execute(
            "SELECT s.id, s.case_number, s.insurer, s.service_type, s.vehicle_type, s.zone, s.distance_km,"
            " s.amount_eur, s.published_at, s.status, s.response_seconds, u.code AS unit_code, u.driver,"
            " (SELECT e.message FROM events e WHERE e.service_id = s.id ORDER BY e.id DESC LIMIT 1) AS reason"
            " FROM services s LEFT JOIN jobs j ON j.service_id = s.id LEFT JOIN units u ON u.id = j.unit_id"
            " WHERE s.first_seen >= ? ORDER BY s.published_at DESC LIMIT ?",
            (start_of_today(), limit),
        )
        return [dict(r) for r in rows]

    def waiting_service_ids(self) -> set[int]:
        return {r["id"] for r in self._conn.execute("SELECT id FROM services WHERE status = 'waiting'")}

    # ---- jobs ------------------------------------------------------------
    def add_job(self, job: Job) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO jobs (service_id, unit_id, assigned_at, travel_seconds, work_seconds, start_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (job.service_id, job.unit_id, job.assigned_at, job.travel_seconds, job.work_seconds, job.starts_at),
            )

    def recent_jobs(self, since: float) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE MAX(start_at, assigned_at) + travel_seconds + work_seconds > ?"
            " ORDER BY MAX(start_at, assigned_at)",
            (since,),
        )
        return [Job(r["service_id"], r["unit_id"], r["assigned_at"], r["travel_seconds"], r["work_seconds"],
                    r["start_at"]) for r in rows]

    def count_jobs_today(self) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT unit_id, COUNT(*) AS n FROM jobs WHERE assigned_at >= ? GROUP BY unit_id", (start_of_today(),)
        )
        return {r["unit_id"]: r["n"] for r in rows}

    # ---- events ----------------------------------------------------------
    def add_event(self, kind: str, message: str, service_id: int | None = None, unit_id: int | None = None) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO events (kind, message, service_id, unit_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (kind, message, service_id, unit_id, time.time()),
            )

    def recent_events(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT e.*, s.case_number, s.service_type, s.zone, s.amount_eur, s.vehicle_type, s.distance_km,"
            " u.code AS unit_code, u.driver"
            " FROM events e LEFT JOIN services s ON s.id = e.service_id LEFT JOIN units u ON u.id = e.unit_id"
            " ORDER BY e.id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    # ---- settings --------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def is_paused(self) -> bool:
        return self.get_setting("bot_paused", "0") == "1"

    def max_queue_wait(self, default: float) -> float:
        try:
            return float(self.get_setting("max_queue_wait_s", str(default)))
        except ValueError:
            return default

    # ---- stats -----------------------------------------------------------
    def stats_today(self) -> dict[str, float]:
        since = start_of_today()
        row = self._conn.execute(
            "SELECT"
            " COUNT(*) AS seen,"
            " SUM(status = 'accepted') AS accepted,"
            " SUM(status = 'rejected') AS rejected,"
            " SUM(status = 'lost') AS lost,"
            " SUM(status = 'failed') AS failed,"
            " COALESCE(SUM(CASE WHEN status = 'accepted' THEN amount_eur END), 0) AS revenue,"
            " AVG(CASE WHEN status = 'accepted' THEN response_seconds END) AS avg_response"
            " FROM services WHERE first_seen >= ?",
            (since,),
        ).fetchone()
        return {k: (row[k] or 0) for k in row.keys()}
