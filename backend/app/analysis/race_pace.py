from typing import Any

from app.analysis.common import clean_laps, grouped, lap_statistics, most_common
from app.models.domain import RacePaceDriverRow, RacePaceResult


def calculate_race_pace(session_id: str, laps: list[dict[str, Any]]) -> RacePaceResult:
    clean = clean_laps(laps)
    caveats = [
        "Lap 1, pit-in, pit-out, deleted, inaccurate, safety car, VSC, and red flag laps are excluded."
    ]
    if len(clean) < len(laps):
        caveats.append(f"Excluded {len(laps) - len(clean)} laps from the pace sample.")

    driver_rows = _pace_rows(grouped(clean, ("driver_code",)), best_scope="driver")
    stint_rows = _pace_rows(grouped(clean, ("driver_code", "stint")), best_scope="stint")
    return RacePaceResult(session_id=session_id, drivers=driver_rows, stints=stint_rows, caveats=caveats)


def _pace_rows(
    lap_groups: dict[tuple[Any, ...], list[dict[str, Any]]], best_scope: str
) -> list[RacePaceDriverRow]:
    base_rows: list[RacePaceDriverRow] = []
    for key, laps in lap_groups.items():
        stats = lap_statistics(laps)
        driver_code = str(key[0])
        stint = int(key[1]) if len(key) > 1 and key[1] is not None else None
        base_rows.append(
            RacePaceDriverRow(
                driver_code=driver_code,
                compound=most_common([lap.get("compound") for lap in laps]),
                stint=stint,
                **stats,
            )
        )

    valid_medians = [
        row.median_lap_ms for row in base_rows if row.median_lap_ms is not None and row.lap_count > 0
    ]
    best = min(valid_medians) if valid_medians else None
    rows = []
    for row in base_rows:
        gap = None
        if best is not None and row.median_lap_ms is not None:
            gap = row.median_lap_ms - best
        rows.append(row.model_copy(update={"gap_to_best_ms": gap}))

    return sorted(rows, key=lambda row: (row.gap_to_best_ms is None, row.gap_to_best_ms or 0, row.driver_code))

