"""Domain models shared by the bot and the control panel."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Operator(StrEnum):
    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


# Service fields that rules may reference, with a human label for the panel.
RULE_FIELDS: dict[str, str] = {
    "service_type": "Tipo de servicio",
    "zone": "Zona",
    "distance_km": "Kilómetros",
    "amount_eur": "Importe (€)",
    "insurer": "Aseguradora",
    "vehicle_type": "Tipo de vehículo",
}
NUMERIC_FIELDS: frozenset[str] = frozenset({"distance_km", "amount_eur"})


class UnitType(StrEnum):
    LIGHT_TOW = "grua_ligera"  # flatbed for cars, motorbikes and 4x4
    HEAVY_TOW = "grua_pesada"  # flatbed for vans and anything lighter
    ASSIST = "asistencia"  # roadside assistance van (no towing)


UNIT_TYPE_LABELS: dict[UnitType, str] = {
    UnitType.LIGHT_TOW: "Grúa ligera",
    UnitType.HEAVY_TOW: "Grúa pesada",
    UnitType.ASSIST: "Asistencia en carretera",
}


@dataclass(frozen=True, slots=True)
class Service:
    id: int
    case_number: str
    insurer: str
    service_type: str
    vehicle_type: str
    vehicle_model: str
    plate: str
    zone: str
    address: str
    destination: str
    distance_km: float
    amount_eur: float
    published_at: float


@dataclass(frozen=True, slots=True)
class Rule:
    id: int
    name: str
    field: str
    operator: Operator
    value: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class Unit:
    id: int
    code: str  # e.g. "G-03", what the bot types into the platform
    driver: str
    unit_type: UnitType
    base_zone: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class Job:
    service_id: int
    unit_id: int
    assigned_at: float
    travel_seconds: float
    work_seconds: float
    start_at: float = 0.0  # when the unit sets off; later than assigned_at if it was queued

    @property
    def starts_at(self) -> float:
        return max(self.start_at, self.assigned_at)

    @property
    def finishes_at(self) -> float:
        return self.starts_at + self.travel_seconds + self.work_seconds


@dataclass(frozen=True, slots=True)
class Decision:
    service_id: int
    accepted: bool
    reason: str
