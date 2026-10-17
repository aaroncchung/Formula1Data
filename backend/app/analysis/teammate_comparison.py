"""Intra-team lap-time comparison. Returns plain dictionaries."""

from collections import Counter, defaultdict
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
    # A driver with no known team has no team-mate. They used to be pooled
    # under "Unknown" and compared with each other.
    driver_team = {
        driver["code"]: team
        for driver in drivers
        if driver.get("code")
        and (team := (driver.get("team") or {}).get("name"))
        and team != "Unknown"
    }
    clean: dict[str, dict[int, float]] = defaultdict(dict)
    # Teams in the order their first clean lap comes in the timing, then any
    # with none, in the order of the driver list.
    order: dict[str, None] = {}
    for lap in clean_laps(laps):
        driver = lap.get("driver_code")
        number = lap_number(lap)
        team = driver_team.get(driver)
        if not driver or number is None or not team:
            continue
        clean[driver][number] = float(lap["lap_time_ms"])
        order.setdefault(team, None)
    by_team: dict[str, list[str]] = defaultdict(list)
    for driver, team in driver_team.items():
        by_team[team].append(driver)
        order.setdefault(team, None)
    laps_run = Counter(lap.get("driver_code") for lap in laps)

    rows = []
    not_run = []
    for team in order:
        team_drivers = by_team[team]
        if len(team_drivers) < 2:
            continue
        # Two cars per team is the rule; if the data ever lists more, compare
        # the two with the most clean laps rather than guessing at a pairing.
        first, second = sorted(
            sorted(team_drivers), key=lambda code: (len(clean[code]), laps_run[code]), reverse=True
        )[:2]
        if not laps_run[first] and not laps_run[second]:
            not_run.append(team)
            continue
        row = _compare(team, first, clean[first], second, clean[second])
        # A team with a driver who has no clean lap used to have no row, and
        # nothing said so: in 9 of the 24 races of 2025, among them the
        # Austrian GP, which lost Mercedes, Red Bull and Williams to two cars
        # out on lap 1 and one that did not start. Its row has no figures,
        # and says why.
        without = [code for code in sorted((first, second)) if not clean[code]]
        if without:
            why = "; ".join(_no_clean_lap(code, laps_run[code]) for code in without)
            row["caveat"] = f"No gap: {why}."
        rows.append(row)

    caveats = [
        "Team-mates are compared on matched laps only: the same lap number, with both laps "
        "clean (lap 1, pit, deleted, inaccurate and neutralised laps are excluded).",
        "The gap is a trimmed mean of the lap-by-lap differences: the "
        f"{TRIM_FRACTION:.0%} of matched laps with the largest difference each way, and "
        "never fewer than one lap each way, are dropped, and each driver's average is over "
        f"the laps that remain. At least {MIN_MATCHED_LAPS} matched laps are required.",
        "Team-mates on different strategies differ by a second or more from lap to lap, so a "
        "gap that is small against the lap-to-lap spread is not a real difference.",
        "Matching by lap number assumes both cars are on track together, which holds in a "
        "race or sprint but not in practice or qualifying.",
    ]
    if not any(all(driver["clean_lap_count"] for driver in row["drivers"]) for row in rows):
        caveats.append("No team had two drivers with clean laps.")
    # Stroll did not start the 2025 Spanish GP, and is not in its driver list.
    alone = [team for team in order if len(by_team[team]) == 1]
    for teams, why in ((alone, "the session has one driver of"), (not_run, "neither driver ran a lap for")):
        if teams:
            which = "the team" if len(teams) == 1 else "each"
            caveats.append(f"No row for {', '.join(teams)}: {why} {which}.")
    return {"session_id": session_id, "rows": rows, "caveats": caveats}


def _no_clean_lap(driver: str, laps_run: int) -> str:
    """Why a driver has no clean lap to compare, as far as the lap count says."""
    if not laps_run:
        return f"{driver} ran no lap"
    if laps_run == 1:
        return f"{driver}'s one lap is not a clean lap"
    return f"none of {driver}'s {laps_run} laps is a clean lap"


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
