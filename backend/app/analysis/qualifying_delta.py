from typing import Any

from app.analysis.telemetry_compare import compare_telemetry
from app.models.domain import QualifyingDeltaResult


def calculate_qualifying_delta(
    session_id: str,
    laps: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    driver_a: str,
    driver_b: str,
) -> QualifyingDeltaResult:
    fastest_a = _fastest_lap(laps, driver_a)
    fastest_b = _fastest_lap(laps, driver_b)
    caveats: list[str] = []
    if fastest_a is None or fastest_b is None:
        return QualifyingDeltaResult(
            session_id=session_id,
            driver_a=driver_a.upper(),
            driver_b=driver_b.upper(),
            sector_delta_ms={},
            telemetry=None,
            caveats=["A fastest lap could not be found for one or both drivers."],
        )

    sectors = {
        "sector_1": _delta(fastest_a, fastest_b, "sector_1_ms"),
        "sector_2": _delta(fastest_a, fastest_b, "sector_2_ms"),
        "sector_3": _delta(fastest_a, fastest_b, "sector_3_ms"),
        "lap": _delta(fastest_a, fastest_b, "lap_time_ms"),
    }
    telemetry_result = compare_telemetry(
        session_id,
        telemetry,
        laps,
        drivers,
        driver_a,
        int(fastest_a["lap_number"]),
        driver_b,
        int(fastest_b["lap_number"]),
    )
    if telemetry_result is None:
        caveats.append("Telemetry is missing for at least one selected fastest lap.")
    return QualifyingDeltaResult(
        session_id=session_id,
        driver_a=driver_a.upper(),
        driver_b=driver_b.upper(),
        sector_delta_ms=sectors,
        telemetry=telemetry_result,
        caveats=caveats,
    )


def _fastest_lap(laps: list[dict[str, Any]], driver: str) -> dict[str, Any] | None:
    driver_laps = [
        lap
        for lap in laps
        if lap.get("driver_code") == driver.upper()
        and lap.get("lap_time_ms") is not None
        and not lap.get("is_deleted")
    ]
    if not driver_laps:
        return None
    return min(driver_laps, key=lambda lap: lap["lap_time_ms"])


def _delta(lap_a: dict[str, Any], lap_b: dict[str, Any], field: str) -> int | None:
    if lap_a.get(field) is None or lap_b.get(field) is None:
        return None
    return int(lap_b[field]) - int(lap_a[field])

