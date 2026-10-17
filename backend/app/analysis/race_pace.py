"""Race-pace aggregation per driver and per stint.

Returns plain dictionaries; ``app/api/routes/analysis.py`` wraps the result in
``RacePaceResult`` and the pipeline writes it straight to JSON.
"""

import math
from typing import Any

from .common import clean_laps, grouped, lap_statistics, most_common


# A median is given a gap to the best only when it is over enough laps to be
# compared with the others. Fewer than five clean laps is a handful of laps,
# not a pace: five is the long-run threshold the pace prediction and the
# team-mate comparison use. That is the least for a stint's row.
MIN_RANKED_LAPS = 5
# And a driver's median is over their own clean laps, so one who stopped early
# has a median of the opening part of the race, on more fuel. In the 2025
# Mexico City GP Lawson, out after five laps, was ranked 3.0 s off the best on
# one clean lap; in the 2025 United States GP Sainz on four. Over the 2025
# races a full-distance driver's median over the first half of their own clean
# laps is 0.62 s slower than over all of them, over the first quarter 0.90 s
# and over the first tenth 1.07 s. So a driver is ranked only with at least
# half as many clean laps as the driver with the most. That is a compromise: a
# driver just over it is still a few tenths out. Asking more would leave out
# drivers who finished: Stroll took the flag in the 2026 Australian GP with
# 29 clean laps to the most 50, and Russell in the 2025 Bahrain GP with 30.
MIN_RANKED_SHARE = 0.5


def calculate_race_pace(session_id: str, laps: list[dict[str, Any]]) -> dict[str, Any]:
    clean = clean_laps(laps)
    caveats = [
        "Lap 1, pit-in, pit-out, deleted, inaccurate, safety car, VSC, and red flag laps are excluded.",
        "Each driver's figures are over their own clean laps, which need not be the laps another "
        "driver's are over: a driver who stopped early ran only the first part of the race, on "
        "more fuel.",
    ]
    if len(clean) < len(laps):
        caveats.append(f"Excluded {len(laps) - len(clean)} laps from the pace sample.")

    by_driver = grouped(clean, ("driver_code",))
    most = max((len(group) for group in by_driver.values()), default=0)
    least = max(MIN_RANKED_LAPS, math.ceil(MIN_RANKED_SHARE * most))
    drivers = pace_rows(by_driver, least)
    unranked = [row for row in drivers if row["gap_to_best_ms"] is None and row["lap_count"]]
    if unranked:
        caveats.append(
            "A driver has a gap to the best only with at least half as many clean laps as the "
            f"driver with the most, who has {most}, and at least {MIN_RANKED_LAPS}. No gap for "
            + ", ".join(f"{row['driver_code']} ({row['lap_count']})" for row in unranked)
            + "."
        )

    # A lap F1's tyre data gives no stint for is on a set that is not known.
    # It used to make a row of its own, with a stint of null, which is how a
    # row for the whole race is marked: in the 2025 Miami GP, where the tyre
    # data begins on lap 25, one for each of 15 drivers.
    in_a_stint = [lap for lap in clean if lap.get("stint") is not None]
    stints = pace_rows(grouped(in_a_stint, ("driver_code", "stint")), MIN_RANKED_LAPS)
    caveats.append(
        f"A stint has a gap to the best stint only with at least {MIN_RANKED_LAPS} clean laps."
    )
    no_stint = sorted({str(lap.get("driver_code")) for lap in clean if lap.get("stint") is None})
    if no_stint:
        caveats.append(
            f"F1's tyre data gives no stint for {len(clean) - len(in_a_stint)} clean laps, of "
            f"{', '.join(no_stint)}. They are in the drivers' rows and in no stint's."
        )
    return {
        "session_id": session_id,
        "drivers": drivers,
        "stints": stints,
        "caveats": caveats,
    }


def pace_rows(
    lap_groups: dict[tuple[Any, ...], list[dict[str, Any]]], min_laps: int = MIN_RANKED_LAPS
) -> list[dict[str, Any]]:
    """A row of figures for each group of laps, and a gap to the best of the rows of ``min_laps`` or more.

    A row of fewer has no gap, and comes after the rows that have one.
    """
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

    def ranked(row: dict[str, Any]) -> bool:
        return row["median_lap_ms"] is not None and row["lap_count"] >= max(min_laps, 1)

    valid_medians = [row["median_lap_ms"] for row in base_rows if ranked(row)]
    best = min(valid_medians) if valid_medians else None
    rows = []
    for row in base_rows:
        gap = None
        if best is not None and ranked(row):
            gap = row["median_lap_ms"] - best
        rows.append({**row, "gap_to_best_ms": gap})
    return sorted(
        rows,
        key=lambda row: (row["gap_to_best_ms"] is None, row["gap_to_best_ms"] or 0, row["driver_code"]),
    )
