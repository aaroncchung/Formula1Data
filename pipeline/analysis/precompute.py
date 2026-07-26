from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any

from backend.app.analysis.advanced import (
    calculate_car_performance,
    calculate_corner_analysis,
    calculate_fuel_adjusted_tyre_degradation,
    calculate_pace_prediction,
    calculate_track_dominance,
)


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
REPLAY_INTERVAL_MS = 5000
MAX_REPLAY_FRAMES = 2000


def precompute_session_analysis(session_id: str, bundle: dict[str, Any]) -> dict[str, Any]:
    laps = bundle.get("laps", [])
    drivers = bundle.get("drivers", [])
    stints = bundle.get("stints", [])
    pit_stops = bundle.get("pit_stops", [])
    race_control = bundle.get("race_control", [])
    telemetry = bundle.get("telemetry", [])
    summary = bundle.get("summary", {})

    return {
        "lap-times": lap_time_series(laps, drivers),
        "race-pace": calculate_race_pace(session_id, laps),
        "tyre-degradation": calculate_fuel_adjusted_tyre_degradation(
            session_id, summary, laps
        ),
        "strategy": calculate_strategy(session_id, stints, pit_stops, laps, race_control),
        "ideal-laps": calculate_ideal_laps(session_id, laps),
        "team-mate-comparison": calculate_teammate_comparison(session_id, laps, drivers),
        "track-dominance": calculate_track_dominance(session_id, laps, telemetry),
        "corner-analysis": calculate_corner_analysis(session_id, laps, telemetry),
        "car-performance": calculate_car_performance(session_id, laps, telemetry, drivers),
        "pace-prediction": calculate_pace_prediction(session_id, summary, laps, drivers),
    }


def precompute_position_replay(session_id: str, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return build_position_replay(session_id, bundle.get("telemetry", []))


def lap_time_series(laps: list[dict[str, Any]], drivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_driver: dict[str, dict[str, Any]] = {}
    driver_colors = {
        driver["code"]: driver.get("team", {}).get("color")
        for driver in drivers
        if driver.get("code")
    }
    for lap in laps:
        if lap.get("lap_time_ms") is None:
            continue
        row = by_driver.setdefault(
            lap["driver_code"],
            {"x": [], "y": [], "color": driver_colors.get(lap["driver_code"])},
        )
        row["x"].append(lap["lap_number"])
        row["y"].append(lap["lap_time_ms"])
    return [
        {
            "name": driver,
            "x": row["x"],
            "y": row["y"],
            "color": row["color"],
            "metadata": {},
        }
        for driver, row in sorted(by_driver.items())
    ]


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


def calculate_tyre_degradation(session_id: str, laps: list[dict[str, Any]]) -> dict[str, Any]:
    return calculate_fuel_adjusted_tyre_degradation(session_id, {}, laps)


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
        # dict.get(key, default) only substitutes the default when the key is
        # absent, so a present-but-null lap number used to reach min() and
        # int() unguarded. Drop stops with no usable lap number instead.
        stop_laps = [
            lap_number
            for lap_number in (stop_lap_number(stop) for stop in stops)
            if lap_number is not None
        ]
        if not stop_laps:
            continue
        first_stop_lap = min(stop_laps)
        before = nearest_clean_lap_time(laps, driver, first_stop_lap, -1)
        after = nearest_clean_lap_time(laps, driver, first_stop_lap, 1)
        undercut_overcut.append(
            {
                "driver_code": driver,
                "stop_lap": first_stop_lap,
                "first_clean_lap_gain_ms": before - after
                if before is not None and after is not None
                else None,
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


def calculate_ideal_laps(session_id: str, laps: list[dict[str, Any]]) -> dict[str, Any]:
    by_driver: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lap in laps:
        if lap.get("driver_code"):
            by_driver[lap["driver_code"]].append(lap)

    rows = []
    for driver, driver_laps in by_driver.items():
        best_s1 = min_field(driver_laps, "sector_1_ms")
        best_s2 = min_field(driver_laps, "sector_2_ms")
        best_s3 = min_field(driver_laps, "sector_3_ms")
        best_lap = min_field(driver_laps, "lap_time_ms")
        complete = all(value is not None for value in [best_s1, best_s2, best_s3])
        ideal = sum(value for value in [best_s1, best_s2, best_s3] if value is not None)
        rows.append(
            {
                "driver_code": driver,
                "best_sector_1_ms": best_s1,
                "best_sector_2_ms": best_s2,
                "best_sector_3_ms": best_s3,
                "ideal_lap_ms": ideal if complete else None,
                "best_lap_ms": best_lap,
                "delta_to_ideal_ms": best_lap - ideal if best_lap is not None and complete else None,
            }
        )
    return {"session_id": session_id, "rows": sorted(rows, key=lambda row: row["ideal_lap_ms"] or 999999)}


def calculate_teammate_comparison(
    session_id: str, laps: list[dict[str, Any]], drivers: list[dict[str, Any]]
) -> dict[str, Any]:
    driver_team = {
        driver["code"]: driver.get("team", {}).get("name", "Unknown")
        for driver in drivers
        if driver.get("code")
    }
    by_team: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for lap in clean_laps(laps):
        team = driver_team.get(lap["driver_code"], "Unknown")
        by_team[team][lap["driver_code"]].append(lap["lap_time_ms"])

    rows = []
    for team, team_drivers in by_team.items():
        if len(team_drivers) < 2:
            continue
        ordered = sorted(
            [
                {
                    "driver_code": driver,
                    "average_lap_ms": round(mean(values), 1),
                    "lap_count": len(values),
                }
                for driver, values in team_drivers.items()
                if values
            ],
            key=lambda row: row["average_lap_ms"],
        )
        if len(ordered) >= 2:
            rows.append(
                {
                    "team": team,
                    "drivers": ordered,
                    "gap_ms": round(ordered[1]["average_lap_ms"] - ordered[0]["average_lap_ms"], 1),
                }
            )
    return {
        "session_id": session_id,
        "rows": rows,
        "caveats": ["Sample data may include one driver per team, so this view can be empty."],
    }


def build_position_replay(session_id: str, telemetry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with_position = [
        row
        for row in telemetry
        if row.get("x") is not None and row.get("y") is not None
        and (row.get("session_time_ms") is not None or row.get("relative_time_ms") is not None)
    ]
    if not with_position:
        return []

    session_timed = [row for row in with_position if row.get("session_time_ms") is not None]
    use_session_time = bool(session_timed)
    rows = session_timed if use_session_time else with_position
    by_frame = group_replay_rows(rows, use_session_time)
    frames = []
    ordered_frames = bounded_replay_frames(sorted(by_frame.items()))
    for frame_index, (frame_key, positions_by_driver) in enumerate(ordered_frames):
        positions = [
            {key: value for key, value in position.items() if not key.startswith("_")}
            for position in sorted(positions_by_driver.values(), key=lambda row: row["driver_code"])
        ]
        lap_numbers = {position.get("_lap_number") for position in positions_by_driver.values()}
        lap_number = next(iter(lap_numbers)) if len(lap_numbers) == 1 else None
        if use_session_time:
            timestamp_ms = int(frame_key) * REPLAY_INTERVAL_MS
        else:
            timestamp_ms = frame_index * REPLAY_INTERVAL_MS
            for position in positions:
                position["timing_basis"] = "lap-relative approximation"
                position["timing_caveat"] = (
                    "SessionTime was unavailable; drivers are aligned by lap number and lap-relative time."
                )
        frames.append(
            {
                "session_id": session_id,
                "frame_index": frame_index,
                "lap_number": lap_number,
                "timestamp_ms": timestamp_ms,
                "positions": positions,
            }
        )
    return frames


def group_replay_rows(
    rows: list[dict[str, Any]], use_session_time: bool
) -> dict[Any, dict[str, dict[str, Any]]]:
    by_frame: dict[Any, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        lap_number = int(row.get("lap_number") or 0)
        driver = str(row.get("driver_code") or "").upper()
        timing = row.get("session_time_ms") if use_session_time else row.get("relative_time_ms")
        if not driver or timing is None or (not use_session_time and lap_number <= 0):
            continue
        timing = int(timing)
        time_bin = timing // REPLAY_INTERVAL_MS
        key = time_bin if use_session_time else (lap_number, time_bin)
        candidate = {
            "driver_code": driver,
            "x": row["x"],
            "y": row["y"],
            "speed_kph": row.get("speed_kph"),
            "distance_m": row.get("distance_m"),
            "_timing_ms": timing,
            "_lap_number": lap_number or None,
        }
        current = by_frame[key].get(driver)
        target = (time_bin + 0.5) * REPLAY_INTERVAL_MS
        if current is None or abs(timing - target) < abs(current["_timing_ms"] - target):
            by_frame[key][driver] = candidate
    return by_frame


def bounded_replay_frames(frames: list[Any]) -> list[Any]:
    if len(frames) <= MAX_REPLAY_FRAMES:
        return frames
    return [
        frames[round(index * (len(frames) - 1) / (MAX_REPLAY_FRAMES - 1))]
        for index in range(MAX_REPLAY_FRAMES)
    ]


def clean_laps(laps: list[dict[str, Any]], exclude_first_lap: bool = True) -> list[dict[str, Any]]:
    rows = []
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
        status = str(lap.get("track_status") or "").upper().strip()
        if status in NEUTRALIZED_STATUSES or any(code in status for code in ("4", "5", "6", "7")):
            continue
        rows.append(lap)
    return rows


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


def linear_fit(samples: list[tuple[int | float, int | float]]) -> tuple[float, float | None]:
    x_values = [float(sample[0]) for sample in samples]
    y_values = [float(sample[1]) for sample in samples]
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    slope = (
        sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values, strict=True))
        / denominator
        if denominator
        else 0.0
    )
    intercept = y_mean - slope * x_mean
    fitted = [slope * x + intercept for x in x_values]
    residual = sum((y - fit) ** 2 for y, fit in zip(y_values, fitted, strict=True))
    total = sum((y - y_mean) ** 2 for y in y_values)
    r_squared = 1 - residual / total if total else None
    return float(slope), float(r_squared) if r_squared is not None else None


def stop_lap_number(stop: dict[str, Any]) -> int | None:
    value = stop.get("lap_number")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def nearest_clean_lap_time(
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


def min_field(rows: list[dict[str, Any]], field: str) -> int | None:
    values = [row[field] for row in rows if row.get(field) is not None and not row.get("is_deleted")]
    return min(values) if values else None

