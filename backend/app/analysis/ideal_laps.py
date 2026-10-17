"""Best-sector "ideal lap" per driver. Returns plain dictionaries."""

from typing import Any

from .common import clean_laps


def calculate_ideal_laps(session_id: str, laps: list[dict[str, Any]]) -> dict[str, Any]:
    """Each driver's best three sectors added up, against their best lap.

    Both are taken from the driver's clean laps (``clean_laps``: not lap 1,
    not a pit lap, not deleted, not inaccurate, not neutralised). They used to
    be taken from every lap that was not deleted, and the ideal lap could then
    be slower than the best one: lap 1 has no first sector from the line, and
    an in-lap or an out-lap has the pit lane in it. In the 2025 Las Vegas GP
    Bortoleto ran lap 1 and an in-lap and retired; his ideal lap of 2:23.044,
    a sector of each, was 12.618 s slower than his lap 1.

    Every driver with a lap has a row, and one with no clean lap has no
    figures in it. The time left on track is given only where the ideal lap
    is no slower than the best lap. It can be slower only where F1 gives a
    lap's time and not all of its sectors, or sectors that do not add up to
    it: over the clean laps of the 2025 races it never is.
    """
    by_driver: dict[str, list[dict[str, Any]]] = {}
    for lap in laps:
        if lap.get("driver_code"):
            by_driver.setdefault(lap["driver_code"], [])
    for lap in clean_laps(laps):
        if lap.get("driver_code"):
            by_driver[lap["driver_code"]].append(lap)

    rows = []
    for driver, driver_laps in by_driver.items():
        best_s1 = _min_field(driver_laps, "sector_1_ms")
        best_s2 = _min_field(driver_laps, "sector_2_ms")
        best_s3 = _min_field(driver_laps, "sector_3_ms")
        best_lap = _min_field(driver_laps, "lap_time_ms")
        sectors = (best_s1, best_s2, best_s3)
        ideal = sum(sectors) if None not in sectors else None  # type: ignore[arg-type]
        rows.append(
            {
                "driver_code": driver,
                "best_sector_1_ms": best_s1,
                "best_sector_2_ms": best_s2,
                "best_sector_3_ms": best_s3,
                "ideal_lap_ms": ideal,
                "best_lap_ms": best_lap,
                "delta_to_ideal_ms": best_lap - ideal
                if best_lap is not None and ideal is not None and ideal <= best_lap
                else None,
            }
        )
    return {"session_id": session_id, "rows": sorted(rows, key=lambda row: row["ideal_lap_ms"] or 999999)}


def _min_field(rows: list[dict[str, Any]], field: str) -> int | None:
    values = [row[field] for row in rows if row.get(field) is not None]
    return min(values) if values else None
