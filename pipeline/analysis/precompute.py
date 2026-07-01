from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any


NEUTRALIZED_STATUSES = {"SC", "VSC", "RED", "RED FLAG", "SAFETY CAR"}


def precompute_session_analysis(session_id: str, bundle: dict[str, Any]) -> dict[str, Any]:
    laps = bundle.get("laps", [])
    drivers = bundle.get("drivers", [])
    stints = bundle.get("stints", [])
    pit_stops = bundle.get("pit_stops", [])
    race_control = bundle.get("race_control", [])

    return {
        "lap-times": lap_time_series(laps, drivers),
        "race-pace": calculate_race_pace(session_id, laps),
        "tyre-degradation": calculate_tyre_degradation(session_id, laps),
        "strategy": calculate_strategy(session_id, stints, pit_stops, laps, race_control),
        "ideal-laps": calculate_ideal_laps(session_id, laps),
        "team-mate-comparison": calculate_teammate_comparison(session_id, laps, drivers),
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
    rows = []
    for (driver_code, stint, compound), group_laps in grouped(
        clean_laps(laps), ("driver_code", "stint", "compound")
    ).items():
        samples = [
            (lap.get("tyre_age"), lap.get("lap_time_ms"))
            for lap in group_laps
            if lap.get("tyre_age") is not None and lap.get("lap_time_ms") is not None
        ]
        if len(samples) < 3:
            rows.append(
                {
                    "driver_code": str(driver_code),
                    "compound": str(compound),
                    "stint": int(stint or 0),
                    "degradation_ms_per_lap": None,
                    "r_squared": None,
                    "sample_count": len(samples),
                    "stint_length": len(group_laps),
                    "caveats": ["At least three clean laps are required for a degradation fit."],
                }
            )
            continue

        slope, r_squared = linear_fit(samples)
        caveats = []
        if r_squared is not None and r_squared < 0.5:
            caveats.append("Low fit quality; treat the slope as directional only.")
        rows.append(
            {
                "driver_code": str(driver_code),
                "compound": str(compound),
                "stint": int(stint or 0),
                "degradation_ms_per_lap": round(slope, 2),
                "r_squared": round(r_squared, 3) if r_squared is not None else None,
                "sample_count": len(samples),
                "stint_length": len(group_laps),
                "caveats": caveats,
            }
        )
    return {"session_id": session_id, "rows": rows}


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
        before = lap_time(laps, driver, int(first_stop["lap_number"]) - 1)
        after = lap_time(laps, driver, int(first_stop["lap_number"]) + 1)
        undercut_overcut.append(
            {
                "driver_code": driver,
                "stop_lap": first_stop["lap_number"],
                "first_clean_lap_gain_ms": before - after
                if before is not None and after is not None
                else None,
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
        if row.get("x") is not None and row.get("y") is not None and row.get("relative_time_ms") is not None
    ]
    if not with_position:
        return []

    by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in with_position:
        frame_index = int(row["relative_time_ms"] // 5000)
        by_frame[frame_index].append(
            {
                "driver_code": row["driver_code"],
                "x": row["x"],
                "y": row["y"],
                "speed_kph": row.get("speed_kph"),
                "distance_m": row.get("distance_m"),
            }
        )

    frames = []
    for frame_index, positions in sorted(by_frame.items()):
        lap_number = min((row.get("lap_number") for row in with_position), default=None)
        frames.append(
            {
                "session_id": session_id,
                "frame_index": frame_index,
                "lap_number": lap_number,
                "timestamp_ms": frame_index * 5000,
                "positions": positions,
            }
        )
    return frames


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
        if str(lap.get("track_status") or "").upper() in NEUTRALIZED_STATUSES:
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


def lap_time(laps: list[dict[str, Any]], driver: str, lap_number: int) -> int | None:
    for lap in laps:
        if lap.get("driver_code") == driver and lap.get("lap_number") == lap_number:
            return lap.get("lap_time_ms")
    return None


def min_field(rows: list[dict[str, Any]], field: str) -> int | None:
    values = [row[field] for row in rows if row.get(field) is not None and not row.get("is_deleted")]
    return min(values) if values else None

