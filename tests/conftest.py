from __future__ import annotations

import pytest

from bot.models import Service


def make_service(**overrides: object) -> Service:
    data: dict[str, object] = {
        "id": 1,
        "case_number": "EXP-26-40001",
        "insurer": "Aseguradora Alfa",
        "service_type": "Arrastre",
        "vehicle_type": "Turismo",
        "vehicle_model": "Berlina",
        "plate": "1234 BCD",
        "zone": "Centro",
        "address": "Calle Mayor 1 (Centro)",
        "destination": "Taller concertado (Norte)",
        "distance_km": 12.5,
        "amount_eur": 90.0,
        "published_at": 1000.0,
    }
    data.update(overrides)
    return Service(**data)  # type: ignore[arg-type]


@pytest.fixture
def service() -> Service:
    return make_service()
