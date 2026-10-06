"""Intra-team lap-time comparison. Returns plain dictionaries."""

from collections import defaultdict
from statistics import mean
from typing import Any

from .common import clean_laps, lap_number, robust_spread


# Fewer matched laps than this and the result is a handful of laps, not a
# pace. Five is the long-run threshold the pace prediction already uses.
MIN_MATCHED_LAPS = 5
# Share of the matched laps dropped at each end of the lap-by-lap differences,
# and never fewer than one lap. These are the laps where one car was held up
# (blue flags, traffic, a mistake) and the other was not. In the 2026 Austrian
# GP, up to 6 of a pair's 56 matched laps sat more than two seconds from that
# pair's typical difference.
TRIM_FRACTION = 0.1


def calculate_teammate_comparison(
    session_id: str, laps: list[dict[str, Any]], drivers: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare team-mates on the laps both of them ran cleanly.

    The old method took each driver's mean over all of their own clean laps.
    Those are different laps: a car that retires early is averaged over the
    heavy-fuel opening laps only, and its team-mate over the whole race. In the
    2026 Austrian GP that put Sainz (retired after 23 laps) 272 ms behind
    Albon; on the 18 laps both ran cleanly Sainz was the quicker, by 155 ms.

    Pairing by lap number puts both cars on the same fuel load and the same
    track. The gap is a trimmed mean of the lap-by-lap differences, so it still
    answers "who covered these laps faster" while ignoring the laps where one
    car was held up. Each driver's average is taken over the laps that were
    kept, which makes the gap the difference between the two averages.
    """
    driver_team = {
        driver["code"]: driver.get("team", {}).get("name")
        for driver in drivers
        if driver.get("code")
    }
    by_team: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    for lap in clean_laps(laps):
        driver = lap.get("driver_code")
        number = lap_number(lap)
        # A driver with no known team has no team-mate. They used to be pooled
        # under "Unknown" and compared with each other.
        team = driver_team.get(driver)
        if not driver or number is None or not team or team == "Unknown":
            continue
        by_team[team][driver][number] = float(lap["lap_time_ms"])

    rows = []
    for team, team_drivers in by_team.items():
        if len(team_drivers) < 2:
            continue
        # Two cars per team is the rule; if the data ever lists more, compare
        # the two with the most clean laps rather than guessing at a pairing.
        first, second = sorted(
            sorted(team_drivers), key=lambda code: len(team_drivers[code]), reverse=True
        )[:2]
        rows.append(_compare(team, first, team_drivers[first], second, team_drivers[second]))

    caveats = [
        "Team-mates are compared on matched laps only: the same lap number, with both laps "
        "clean (lap 1, pit, deleted, inaccurate and neutralised laps are excluded).",
        "The gap is a trimmed mean of the lap-by-lap differences: the "
        f"{TRIM_FRACTION:.0%} of matched laps with the largest difference each way are "
        "dropped, and each driver's average is over the laps that remain. At least "
        f"{MIN_MATCHED_LAPS} matched laps are required.",
        "Team-mates on different strategies differ by a second or more from lap to lap, so a "
        "gap that is small against the lap-to-lap spread is not a real difference.",
        "Matching by lap number assumes both cars are on track together, which holds in a "
        "race or sprint but not in practice or qualifying.",
    ]
    if not rows:
        caveats.append("No team had two drivers with clean laps.")
    return {"session_id": session_id, "rows": rows, "caveats": caveats}


def _compare(
    team: str,
    first: str,
    first_laps: dict[int, float],
    second: str,
    second_laps: dict[int, float],
) -> dict[str, Any]:
    matched = sorted(set(first_laps) & set(second_laps))
    deltas = {number: second_laps[number] - first_laps[number] for number in matched}
    kept = _trim(deltas) if len(matched) >= MIN_MATCHED_LAPS else []
    gap = mean(deltas[number] for number in kept) if kept else None
    # List the quicker driver first, as before, so the gap is never negative.
    # With no gap, or a dead heat, the order is alphabetical.
    if gap is not None and gap < 0:
        first, first_laps, second, second_laps = second, second_laps, first, first_laps
        gap = -gap
    elif not gap and second < first:
        first, first_laps, second, second_laps = second, second_laps, first, first_laps

    row: dict[str, Any] = {
        "team": team,
        "drivers": [
            {
                "driver_code": code,
                "average_lap_ms": round(mean(code_laps[n] for n in kept), 1) if kept else None,
                "lap_count": len(kept),
                "clean_lap_count": len(code_laps),
            }
            for code, code_laps in ((first, first_laps), (second, second_laps))
        ],
        "gap_ms": round(gap, 1) if gap is not None else None,
        "gap_spread_ms": _rounded(robust_spread(list(deltas.values()))) if kept else None,
        "matched_lap_count": len(matched),
        "trimmed_lap_count": len(matched) - len(kept) if kept else 0,
    }
    if not kept:
        row["caveat"] = (
            f"Only {len(matched)} matched clean laps; at least {MIN_MATCHED_LAPS} are needed "
            "to report a gap."
        )
    return row


def _trim(deltas: dict[int, float]) -> list[int]:
    """Lap numbers left after dropping the most extreme differences at each end."""
    ordered = sorted(deltas, key=lambda number: (deltas[number], number))
    drop = max(1, int(len(ordered) * TRIM_FRACTION))
    return sorted(ordered[drop : len(ordered) - drop])


def _rounded(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
