from typing import Any

from app.analysis.advanced import calculate_fuel_adjusted_tyre_degradation
from app.models.domain import TyreDegradationResult


def calculate_tyre_degradation(
    session_id: str,
    laps: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
) -> TyreDegradationResult:
    result = calculate_fuel_adjusted_tyre_degradation(session_id, summary or {}, laps)
    return TyreDegradationResult(**result)

