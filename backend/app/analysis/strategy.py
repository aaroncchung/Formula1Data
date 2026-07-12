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
        before = _nearest_clean_lap_time(laps, driver, int(first_stop["lap_number"]), -1)
        after = _nearest_clean_lap_time(laps, driver, int(first_stop["lap_number"]), 1)
        gain = before - after if before is not None and after is not None else None
        undercut_overcut.append(
            {
                "driver_code": driver,
                "stop_lap": first_stop["lap_number"],
                "first_clean_lap_gain_ms": gain,
                "caveat": (
                    "Compares the nearest clean laps before and after the stop; it is not "
                    "adjusted for traffic, tyre warm-up, fuel, or track evolution."
                ),
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
            "Pit duration is pit-lane transit time when FastF1 provides adjacent pit-in/out timestamps.",
            "Undercut/overcut values are descriptive surrounding-lap changes, not causal opponent models.",
        ],
    }


def _nearest_clean_lap_time(
    laps: list[dict[str, Any]], driver: str, stop_lap: int, direction: int
) -> int | None:
    candidates = [
        lap
        for lap in laps
        if lap.get("driver_code") == driver
        and lap.get("lap_time_ms") is not None
        and not lap.get("is_pit_in_lap")
        and not lap.get("is_pit_out_lap")
        and not lap.get("is_deleted")
        and (
            int(lap.get("lap_number") or 0) < stop_lap
            if direction < 0
            else int(lap.get("lap_number") or 0) > stop_lap
        )
    ]
    if candidates:
        closest = min(candidates, key=lambda lap: abs(int(lap["lap_number"]) - stop_lap))
        return closest.get("lap_time_ms")
    return None

