import pytest

from bot.fleet import can_handle, choose_unit, job_progress, plan_job, unit_free_at, zone_distance
from bot.models import Job, Unit, UnitType
from tests.conftest import make_service

LIGHT_CENTRO = Unit(1, "G-01", "Antonio", UnitType.LIGHT_TOW, "Centro")
LIGHT_NORTE = Unit(2, "G-02", "Lucía", UnitType.LIGHT_TOW, "Norte")
HEAVY_SUR = Unit(3, "G-03", "Manuel", UnitType.HEAVY_TOW, "Sur")
ASSIST_ESTE = Unit(4, "A-04", "Carmen", UnitType.ASSIST, "Este")
FLEET = [LIGHT_CENTRO, LIGHT_NORTE, HEAVY_SUR, ASSIST_ESTE]
NOW = 1000.0


def busy_until(unit: Unit, until: float) -> Job:
    """A job that keeps `unit` busy from NOW until `until`."""
    return Job(service_id=99, unit_id=unit.id, assigned_at=NOW, travel_seconds=until - NOW, work_seconds=0, start_at=NOW)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("Norte", "Norte", 0), ("Centro", "Sur", 1), ("Norte", "Este", 2), ("Norte", "Oeste", 2), ("Norte", "Sur", 3)],
)
def test_zone_distance(a: str, b: str, expected: int) -> None:
    assert zone_distance(a, b) == expected == zone_distance(b, a)


def test_assistance_van_cannot_tow() -> None:
    assert not can_handle(UnitType.ASSIST, make_service(service_type="Arrastre"))
    assert can_handle(UnitType.ASSIST, make_service(service_type="Batería"))


def test_van_tow_needs_heavy_truck() -> None:
    van = make_service(service_type="Arrastre", vehicle_type="Furgoneta", zone="Norte")
    assert choose_unit(van, FLEET, [], NOW).unit is HEAVY_SUR  # type: ignore[union-attr]


def test_picks_closest_capable_unit() -> None:
    tow_north = make_service(service_type="Arrastre", zone="Norte")
    assignment = choose_unit(tow_north, FLEET, [], NOW)
    assert assignment is not None and assignment.unit is LIGHT_NORTE and not assignment.queued


def test_keeps_heavy_truck_free_for_heavy_jobs() -> None:
    battery_south = make_service(service_type="Batería", zone="Sur")
    assert choose_unit(battery_south, FLEET, [], NOW).unit is ASSIST_ESTE  # type: ignore[union-attr]


def test_queues_behind_busy_unit_when_none_is_free() -> None:
    van = make_service(service_type="Arrastre", vehicle_type="Furgoneta", zone="Sur")
    assignment = choose_unit(van, FLEET, [busy_until(HEAVY_SUR, NOW + 40)], NOW, max_wait_s=90)
    assert assignment is not None
    assert assignment.unit is HEAVY_SUR and assignment.queued
    assert assignment.start_at == NOW + 40 and assignment.wait_seconds == 40


def test_rejects_when_queue_would_be_too_long() -> None:
    van = make_service(service_type="Arrastre", vehicle_type="Furgoneta", zone="Sur")
    assert choose_unit(van, FLEET, [busy_until(HEAVY_SUR, NOW + 120)], NOW, max_wait_s=90) is None


def test_short_wait_for_a_close_unit_beats_a_free_far_one() -> None:
    tow_north = make_service(service_type="Arrastre", zone="Norte")
    fleet = [LIGHT_NORTE, HEAVY_SUR]  # heavy truck is free but far away and the "wrong" kind
    assignment = choose_unit(tow_north, fleet, [busy_until(LIGHT_NORTE, NOW + 10)], NOW)
    assert assignment is not None and assignment.unit is LIGHT_NORTE and assignment.wait_seconds == 10


def test_inactive_units_are_ignored() -> None:
    tow_north = make_service(service_type="Arrastre", zone="Norte")
    inactive = Unit(2, "G-02", "Lucía", UnitType.LIGHT_TOW, "Norte", active=False)
    assert choose_unit(tow_north, [inactive], [], NOW) is None


def test_unit_free_at() -> None:
    jobs = [busy_until(LIGHT_CENTRO, NOW + 30), busy_until(LIGHT_CENTRO, NOW + 50)]
    assert unit_free_at(LIGHT_CENTRO.id, jobs, NOW) == NOW + 50
    assert unit_free_at(LIGHT_NORTE.id, jobs, NOW) == NOW


def test_job_lifecycle_with_queue() -> None:
    job = plan_job(make_service(service_type="Arrastre", zone="Centro"), LIGHT_CENTRO, now=NOW, start_at=NOW + 20)
    queued = job_progress(job, NOW + 5)
    assert queued.state == "en_cola" and queued.starts_in == 15
    assert job_progress(job, NOW + 21).state == "en_camino"
    assert job_progress(job, NOW + 20 + job.travel_seconds + 1).state == "en_servicio"
    done = job_progress(job, job.finishes_at + 1)
    assert done.state == "finalizado" and done.progress == 1.0
