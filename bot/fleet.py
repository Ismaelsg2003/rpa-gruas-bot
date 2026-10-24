"""Fleet logic: which unit can do a service, which one to send, and job progress.

Times are compressed for the demo (a real 30 km trip lasts seconds, not minutes)
so a viewer can watch a full service lifecycle in under a minute.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from bot.models import Job, Service, Unit, UnitType

OUTER_RING = ["Norte", "Este", "Sur", "Oeste"]

# Seconds of demo time; tweak to make the simulation faster or slower.
TRAVEL_BASE_S = 5.0
TRAVEL_PER_KM_S = 0.4
WORK_S = {"Arrastre": 25.0}
WORK_DEFAULT_S = 12.0


def zone_distance(a: str, b: str) -> int:
    """0 same zone, 1 centre<->outer, 2 neighbouring outer zones, 3 opposite."""
    if a == b:
        return 0
    if "Centro" in (a, b):
        return 1
    if a in OUTER_RING and b in OUTER_RING:
        gap = abs(OUTER_RING.index(a) - OUTER_RING.index(b))
        return 2 if gap in (1, 3) else 3
    return 3


def can_handle(unit_type: UnitType, service: Service) -> bool:
    if service.service_type == "Arrastre":
        if service.vehicle_type == "Furgoneta":
            return unit_type is UnitType.HEAVY_TOW
        return unit_type in (UnitType.LIGHT_TOW, UnitType.HEAVY_TOW)
    # Battery, tyre, fuel, door opening: any unit carries the kit.
    return True


# Lower = preferred. Keep tow trucks free for towing when an assistance van can go.
_PREFERENCE = {
    "Arrastre": {UnitType.LIGHT_TOW: 0, UnitType.HEAVY_TOW: 1, UnitType.ASSIST: 9},
    "_other": {UnitType.ASSIST: 0, UnitType.LIGHT_TOW: 1, UnitType.HEAVY_TOW: 2},
}


# How many seconds of queue we would accept to avoid one point of "score"
# (one zone further away, or using a less suitable kind of unit).
SCORE_SECONDS = 8.0
DEFAULT_MAX_QUEUE_WAIT_S = 90.0


@dataclass(frozen=True, slots=True)
class Assignment:
    unit: Unit
    start_at: float  # when the unit is free to set off
    wait_seconds: float  # 0 if it can go right now

    @property
    def queued(self) -> bool:
        return self.wait_seconds > 0.5


def unit_free_at(unit_id: int, jobs: Iterable[Job], now: float) -> float:
    """When the unit finishes everything already assigned to it (now if idle)."""
    return max([now] + [j.finishes_at for j in jobs if j.unit_id == unit_id])


def choose_unit(
    service: Service,
    units: Iterable[Unit],
    jobs: Iterable[Job],
    now: float,
    max_wait_s: float = DEFAULT_MAX_QUEUE_WAIT_S,
) -> Assignment | None:
    """Best unit for the service, queueing it behind current work if needed.

    Cost = seconds the customer would wait in the queue + a penalty for distance and
    for using a less suitable unit. So a free van next door beats a heavy tow truck
    that is idle in the same zone, and a truck that frees up in 10 s can beat a free
    one on the other side of the city. Returns None if every capable unit would make
    the customer wait longer than max_wait_s.
    """
    jobs = list(jobs)
    prefs = _PREFERENCE.get(service.service_type, _PREFERENCE["_other"])
    best: tuple[tuple[float, int, int], Assignment] | None = None
    for u in units:
        if not (u.active and can_handle(u.unit_type, service)):
            continue
        start = unit_free_at(u.id, jobs, now)
        wait = start - now
        if wait > max_wait_s:
            continue
        score = zone_distance(u.base_zone, service.zone) + prefs[u.unit_type]
        key = (wait + SCORE_SECONDS * score, prefs[u.unit_type], u.id)
        if best is None or key < best[0]:
            best = (key, Assignment(u, start, wait))
    return best[1] if best else None


def plan_job(service: Service, unit: Unit, now: float, start_at: float | None = None) -> Job:
    travel = TRAVEL_BASE_S + service.distance_km * TRAVEL_PER_KM_S + zone_distance(unit.base_zone, service.zone) * 3
    work = WORK_S.get(service.service_type, WORK_DEFAULT_S)
    return Job(service_id=service.id, unit_id=unit.id, assigned_at=now, travel_seconds=round(travel, 1),
               work_seconds=work, start_at=max(now, start_at or now))


@dataclass(frozen=True, slots=True)
class JobProgress:
    state: str  # en_cola | en_camino | en_servicio | finalizado
    label: str
    progress: float  # 0..1 over travel + work
    seconds_left: int  # until the job is finished
    starts_in: int  # seconds until the unit sets off (0 once started)


def job_progress(job: Job, now: float) -> JobProgress:
    left = max(0, int(round(job.finishes_at - now)))
    if now < job.starts_at:
        return JobProgress("en_cola", "En cola", 0.0, left, int(round(job.starts_at - now)))
    elapsed = now - job.starts_at
    total = job.travel_seconds + job.work_seconds
    progress = min(1.0, max(0.0, elapsed / total)) if total else 1.0
    if elapsed < job.travel_seconds:
        return JobProgress("en_camino", "En camino", progress, left, 0)
    if elapsed < total:
        return JobProgress("en_servicio", "En servicio", progress, left, 0)
    return JobProgress("finalizado", "Finalizado", 1.0, 0, 0)
