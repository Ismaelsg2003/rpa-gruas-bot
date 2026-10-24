import sqlite3
from collections.abc import Iterator

import pytest

from bot.db import Database
from bot.models import Job, Operator, UnitType
from bot.rules import RuleError
from tests.conftest import make_service


@pytest.fixture
def db() -> Iterator[Database]:
    database = Database(":memory:")
    yield database
    database.close()


def test_rules_crud(db: Database) -> None:
    rule_id = db.add_rule("Importe mínimo", "amount_eur", "gte", "55")
    [rule] = db.list_rules()
    assert rule.id == rule_id and rule.operator is Operator.GTE

    db.update_rule(rule_id, value="70", active=False)
    assert db.get_rule(rule_id).value == "70"  # type: ignore[union-attr]
    assert db.list_rules(only_active=True) == []

    db.delete_rule(rule_id)
    assert db.list_rules() == []


def test_invalid_rules_rejected(db: Database) -> None:
    with pytest.raises(ValueError):
        db.add_rule("Malo", "customer", "eq", "x")
    with pytest.raises(ValueError):
        db.add_rule("Malo", "zone", "like", "x")
    rule_id = db.add_rule("Importe", "amount_eur", "gte", "55")
    with pytest.raises(RuleError):
        db.update_rule(rule_id, value="mucho")


def test_duplicate_rule_name_rejected(db: Database) -> None:
    db.add_rule("Zona", "zone", "in", "Norte")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_rule("Zona", "zone", "in", "Sur")


def test_service_lifecycle_and_stats(db: Database) -> None:
    unit_id = db.add_unit("G-01", "Antonio", UnitType.LIGHT_TOW, "Centro")
    accepted, rejected = make_service(id=1, amount_eur=100.0), make_service(id=2)

    for s in (accepted, rejected):
        db.record_service(s)
    db.record_service(accepted)  # idempotent
    assert db.service_status(1) == "new"

    db.set_service_status(1, "accepted", response_seconds=2.5)
    db.add_job(Job(1, unit_id, assigned_at=10.0, travel_seconds=5, work_seconds=5))
    db.set_service_status(2, "waiting")
    assert db.waiting_service_ids() == {2}
    db.set_service_status(2, "lost")

    stats = db.stats_today()
    assert (stats["accepted"], stats["lost"], stats["revenue"], stats["avg_response"]) == (1, 1, 100.0, 2.5)
    assert [j.unit_id for j in db.recent_jobs(since=0)] == [unit_id]


def test_queued_job_roundtrip_and_migration(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import sqlite3 as sq

    path = tmp_path / "old.db"
    # A database created by the previous version, without jobs.start_at.
    con = sq.connect(path)
    con.execute("CREATE TABLE jobs (service_id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL,"
                " assigned_at REAL NOT NULL, travel_seconds REAL NOT NULL, work_seconds REAL NOT NULL)")
    con.commit()
    con.close()

    db = Database(path)
    unit_id = db.add_unit("G-01", "Antonio", UnitType.LIGHT_TOW, "Centro")
    db.record_service(make_service(id=1))
    db.add_job(Job(1, unit_id, assigned_at=10.0, travel_seconds=5, work_seconds=5, start_at=40.0))
    [job] = db.recent_jobs(since=0)
    assert job.starts_at == 40.0 and job.finishes_at == 50.0
    db.close()


def test_max_queue_wait_setting(db: Database) -> None:
    assert db.max_queue_wait(90) == 90
    db.set_setting("max_queue_wait_s", "45")
    assert db.max_queue_wait(90) == 45


def test_events_join_service_and_unit(db: Database) -> None:
    unit_id = db.add_unit("G-01", "Antonio", UnitType.LIGHT_TOW, "Centro")
    db.record_service(make_service(id=5))
    db.add_event("accepted", "ok", service_id=5, unit_id=unit_id)
    [event] = db.recent_events()
    assert event["case_number"] == "EXP-26-40001" and event["unit_code"] == "G-01"


def test_pause_setting(db: Database) -> None:
    assert not db.is_paused()
    db.set_setting("bot_paused", "1")
    assert db.is_paused()


def test_services_today_shows_outcome_unit_and_reason(db: Database) -> None:
    unit_id = db.add_unit("G-01", "Antonio", UnitType.LIGHT_TOW, "Centro")
    db.record_service(make_service(id=1, published_at=1.0))
    db.record_service(make_service(id=2, published_at=2.0))
    db.set_service_status(1, "accepted", response_seconds=2.0)
    db.add_job(Job(1, unit_id, assigned_at=10.0, travel_seconds=5, work_seconds=5))
    db.set_service_status(2, "rejected")
    db.add_event("rejected", "No cumple: Importe mínimo", service_id=2)

    rejected, accepted = db.services_today()  # newest first
    assert (rejected["status"], rejected["reason"], rejected["unit_code"]) == ("rejected", "No cumple: Importe mínimo", None)
    assert (accepted["status"], accepted["unit_code"]) == ("accepted", "G-01")
