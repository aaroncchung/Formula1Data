"""Lap filtering and summary statistics shared by every other analysis module."""

from collections import Counter
from statistics import mean, median
from typing import Any


NEUTRALIZED_STATUSES = {
    "4",
    "5",
    "6",
    "7",
    "SC",
    "VSC",
    "RED",
    "RED FLAG",
    "SAFETY CAR",
}


def is_neutralized(track_status: Any) -> bool:
    """True when any part of the lap ran under a safety car, VSC or red flag.

    FastF1 concatenates every status seen during a lap, so "14" is a lap that
    started clear and ended behind the safety car. Any neutralised code in the
    string counts.
    """
    status = str(track_status or "").upper().strip()
    return status in NEUTRALIZED_STATUSES or any(code in status for code in ("4", "5", "6", "7"))


def has_yellow(track_status: Any) -> bool:
    """True when a yellow flag was shown somewhere on track during the lap.

    ``clean_laps`` keeps these laps: the status is session-wide, so a car
    carrying it may never have seen the flag, and a median over a stint absorbs
    the laps that did. A comparison that rests on one named lap cannot. In the
    2026 Austrian GP the two Aston Martins ran 0.9 s and 1.2 s off their own
    pace on lap 23, status "12", the lap before both pitted.
    """
    status = str(track_status or "").upper().strip()
    return "2" in status or "YELLOW" in status


def clean_laps(laps: list[dict[str, Any]], exclude_first_lap: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lap in laps:
        if lap.get("lap_time_ms") is None:
            continue
        if exclude_first_lap and lap.get("lap_number") == 1:
            continue
        if lap.get("is_pit_in_lap") or lap.get("is_pit_out_lap"):
            continue
        if lap.get("is_deleted"):
            continue
        if lap.get("is_accurate") is False:
            continue
        if is_neutralized(lap.get("track_status")):
            continue
        rows.append(lap)
    return rows


def lap_number(row: dict[str, Any]) -> int | None:
    """The row's lap number as an int, or None when it is absent or unusable."""
    value = row.get("lap_number")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def robust_spread(values: list[int | float]) -> float | None:
    """Spread of ``values`` as 1.4826 x the median absolute deviation.

    The factor makes it read like a standard deviation for normally scattered
    data, while one wild value moves it very little.
    """
    if not values:
        return None
    center = median(values)
    return float(1.4826 * median(abs(value - center) for value in values))


def grouped(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    output: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        group_key = tuple(row.get(key) for key in keys)
        output.setdefault(group_key, []).append(row)
    return output


def trimmed_mean(values: list[int | float]) -> float | None:
    if not values:
        return None
    if len(values) < 4:
        return float(mean(values))
    ordered = sorted(values)
    return float(mean(ordered[1:-1]))


def most_common(values: list[Any]) -> Any:
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return Counter(filtered).most_common(1)[0][0]


def lap_statistics(laps: list[dict[str, Any]]) -> dict[str, float | int | None]:
    values = [lap["lap_time_ms"] for lap in laps if lap.get("lap_time_ms") is not None]
    if not values:
        return {
            "median_lap_ms": None,
            "mean_lap_ms": None,
            "trimmed_mean_lap_ms": None,
            "fastest_clean_lap_ms": None,
            "lap_count": 0,
        }
    return {
        "median_lap_ms": float(median(values)),
        "mean_lap_ms": float(mean(values)),
        "trimmed_mean_lap_ms": trimmed_mean(values),
        "fastest_clean_lap_ms": int(min(values)),
        "lap_count": len(values),
    }

