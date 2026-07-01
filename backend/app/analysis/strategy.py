from collections import Counter, defaultdict
from typing import Any


def calculate_strategy(
    session_id: str,
    stints: list[dict[str, Any]],
    pit_stops: list[dict[str, Any]],
    laps: list[dict[str, Any]],
    race_control: list[dict[str, Any]],
) -> dict[str, Any]:
    compound_usage = Counter(stint.get("compound") for stint in stints)
    pit_durations = [stop["duration_ms"] for stop in pit_stops if stop.get("duration_ms") is not None]
    pit_loss_estimate_ms = round(sum(pit_durations) / len(pit_durations), 1) if pit_durations else None

    by_driver: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stop in pit_stops:
        by_driver[stop["driver_code"]].append(stop)

    undercut_overcut = []
    for driver, stops in by_driver.items():
        first_stop = min(stops, key=lambda stop: stop.get("lap_number", 999))
        before = _lap_time(laps, driver, int(first_stop["lap_number"]) - 1)
        after = _lap_time(laps, driver, int(first_stop["lap_number"]) + 1)
        gain = before - after if before is not None and after is not None else None
        undercut_overcut.append(
            {
                "driver_code": driver,
                "stop_lap": first_stop["lap_number"],
                "first_clean_lap_gain_ms": gain,
                "caveat": "Compares surrounding driver laps only; traffic-adjusted modeling is a TODO.",
            }
        )

    return {
        "session_id": session_id,
        "stints": stints,
        "compound_usage": dict(compound_usage),
        "pit_stops": pit_stops,
        "pit_loss_estimate_ms": pit_loss_estimate_ms,
        "undercut_overcut": undercut_overcut,
        "race_control_overlays": race_control,
        "caveats": [
            "Pit loss and undercut/overcut values are simple estimates until full race pace context is available."
        ],
    }


def _lap_time(laps: list[dict[str, Any]], driver: str, lap_number: int) -> int | None:
    for lap in laps:
        if lap.get("driver_code") == driver and lap.get("lap_number") == lap_number:
            return lap.get("lap_time_ms")
    return None

