"""Race-pace aggregation per driver and per stint.

Returns plain dictionaries; ``app/api/routes/analysis.py`` wraps the result in
``RacePaceResult`` and the pipeline writes it straight to JSON.
"""

from typing import Any

from .common import clean_laps, grouped, lap_statistics, most_common


def calculate_race_pace(session_id: str, laps: list[dict[str, Any]]) -> dict[str, Any]:
    clean = clean_laps(laps)
    caveats = [
        "Lap 1, pit-in, pit-out, deleted, inaccurate, safety car, VSC, and red flag laps are excluded."
    ]
    if len(clean) < len(laps):
        caveats.append(f"Excluded {len(laps) - len(clean)} laps from the pace sample.")
    return {
        "session_id": session_id,
        "drivers": pace_rows(grouped(clean, ("driver_code",))),
        "stints": pace_rows(grouped(clean, ("driver_code", "stint"))),
        "caveats": caveats,
    }


def pace_rows(lap_groups: dict[tuple[Any, ...], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    base_rows = []
    for key, laps in lap_groups.items():
        stats = lap_statistics(laps)
        row = {
            "driver_code": str(key[0]),
            "compound": most_common([lap.get("compound") for lap in laps]),
            "stint": int(key[1]) if len(key) > 1 and key[1] is not None else None,
            **stats,
        }
        base_rows.append(row)

    valid_medians = [
        row["median_lap_ms"]
        for row in base_rows
        if row["median_lap_ms"] is not None and row["lap_count"] > 0
    ]
    best = min(valid_medians) if valid_medians else None
    rows = []
    for row in base_rows:
        gap = None
        if best is not None and row["median_lap_ms"] is not None:
            gap = row["median_lap_ms"] - best
        rows.append({**row, "gap_to_best_ms": gap})
    return sorted(
        rows,
        key=lambda row: (row["gap_to_best_ms"] is None, row["gap_to_best_ms"] or 0, row["driver_code"]),
    )
