"""Best-sector "ideal lap" per driver. Returns plain dictionaries."""

from collections import defaultdict
from typing import Any


def calculate_ideal_laps(session_id: str, laps: list[dict[str, Any]]) -> dict[str, Any]:
    by_driver: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lap in laps:
        if lap.get("driver_code"):
            by_driver[lap["driver_code"]].append(lap)

    rows = []
    for driver, driver_laps in by_driver.items():
        best_s1 = _min_field(driver_laps, "sector_1_ms")
        best_s2 = _min_field(driver_laps, "sector_2_ms")
        best_s3 = _min_field(driver_laps, "sector_3_ms")
        best_lap = _min_field(driver_laps, "lap_time_ms")
        ideal = sum(value for value in [best_s1, best_s2, best_s3] if value is not None)
        rows.append(
            {
                "driver_code": driver,
                "best_sector_1_ms": best_s1,
                "best_sector_2_ms": best_s2,
                "best_sector_3_ms": best_s3,
                "ideal_lap_ms": ideal if all(v is not None for v in [best_s1, best_s2, best_s3]) else None,
                "best_lap_ms": best_lap,
                "delta_to_ideal_ms": best_lap - ideal
                if best_lap is not None and all(v is not None for v in [best_s1, best_s2, best_s3])
                else None,
            }
        )
    return {"session_id": session_id, "rows": sorted(rows, key=lambda row: row["ideal_lap_ms"] or 999999)}


def _min_field(rows: list[dict[str, Any]], field: str) -> int | None:
    values = [row[field] for row in rows if row.get(field) is not None and not row.get("is_deleted")]
    return min(values) if values else None

