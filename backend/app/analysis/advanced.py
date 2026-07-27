"""Pure-Python telemetry analyses shared by the API and static artifact pipeline.

The functions in this module deliberately return plain dictionaries.  They avoid
runtime-only dependencies so the static pipeline can use the exact same methods as
the optional FastAPI service.
"""

from __future__ import annotations

from collections import defaultdict
import math
from statistics import mean, median
from typing import Any

from .common import clean_laps


DEFAULT_MINISECTOR_COUNT = 25
DEFAULT_RACE_FUEL_CORRECTION_MS_PER_LAP = 55.0
DEFAULT_SPRINT_FUEL_CORRECTION_MS_PER_LAP = 35.0


def calculate_track_dominance(
    session_id: str,
    laps: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
    minisector_count: int = DEFAULT_MINISECTOR_COUNT,
) -> dict[str, Any]:
    representatives, samples = representative_telemetry_laps(laps, telemetry)
    caveats = [
        "Each driver's fastest non-deleted lap with telemetry is compared.",
        "Minisector time is interpolated at distance boundaries; it is not an FIA timing sector.",
    ]
    if not samples:
        return {
            "session_id": session_id,
            "representative_laps": representatives,
            "minisector_count": 0,
            "minisectors": [],
            "caveats": caveats + ["No usable telemetry laps were available."],
        }

    common_distance = min(float(rows[-1]["distance_m"]) for rows in samples.values())
    if common_distance <= 0:
        return {
            "session_id": session_id,
            "representative_laps": representatives,
            "minisector_count": 0,
            "minisectors": [],
            "caveats": caveats + ["Telemetry did not contain a usable distance axis."],
        }

    count = max(1, min(int(minisector_count), int(common_distance // 100) or 1))
    reference_driver = min(
        representatives,
        key=lambda row: (row.get("lap_time_ms") is None, row.get("lap_time_ms") or math.inf),
    )["driver_code"]
    reference = samples[reference_driver]
    sectors = []
    for index in range(count):
        start = common_distance * index / count
        end = common_distance * (index + 1) / count
        driver_times: dict[str, float] = {}
        for driver, rows in samples.items():
            start_time = _interpolate(rows, start, "_elapsed_ms")
            end_time = _interpolate(rows, end, "_elapsed_ms")
            if start_time is None or end_time is None or end_time < start_time:
                continue
            driver_times[driver] = round(end_time - start_time, 1)

        ordered = sorted(driver_times.items(), key=lambda item: (item[1], item[0]))
        winner = ordered[0] if ordered else (None, None)
        midpoint = (start + end) / 2
        sectors.append(
            {
                "index": index + 1,
                "start_distance_m": round(start, 1),
                "end_distance_m": round(end, 1),
                "midpoint": {
                    "x": _round_or_none(_interpolate(reference, midpoint, "x"), 2),
                    "y": _round_or_none(_interpolate(reference, midpoint, "y"), 2),
                },
                "winner_driver_code": winner[0],
                "segment_time_ms": winner[1],
                "gap_to_next_ms": round(ordered[1][1] - ordered[0][1], 1)
                if len(ordered) > 1
                else None,
                "driver_times_ms": dict(ordered),
            }
        )
    return {
        "session_id": session_id,
        "representative_laps": representatives,
        "minisector_count": len(sectors),
        "minisectors": sectors,
        "caveats": caveats,
    }


def calculate_corner_analysis(
    session_id: str,
    laps: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
) -> dict[str, Any]:
    representatives, samples = representative_telemetry_laps(laps, telemetry)
    caveats = [
        "Corners are inferred from brake application and speed loss, not official circuit geometry.",
        "Entry, apex, and exit values are distance-interpolated from downsampled telemetry.",
    ]
    events: list[dict[str, Any]] = []
    for driver, rows in samples.items():
        events.extend(_braking_events(driver, rows))

    clusters: list[list[dict[str, Any]]] = []
    for event in sorted(events, key=lambda row: row["apex_distance_m"]):
        if not clusters:
            clusters.append([event])
            continue
        center = median(item["apex_distance_m"] for item in clusters[-1])
        if event["apex_distance_m"] - center <= 120:
            clusters[-1].append(event)
        else:
            clusters.append([event])

    corners = []
    for corner_number, cluster in enumerate(clusters, start=1):
        center = float(median(item["apex_distance_m"] for item in cluster))
        by_driver: dict[str, dict[str, Any]] = {}
        for event in cluster:
            existing = by_driver.get(event["driver_code"])
            if existing is None or abs(event["apex_distance_m"] - center) < abs(
                existing["apex_distance_m"] - center
            ):
                by_driver[event["driver_code"]] = event
        driver_rows = []
        for driver, event in sorted(by_driver.items()):
            driver_rows.append(
                {
                    "driver_code": driver,
                    "brake_start_m": round(event["brake_start_m"], 1),
                    "apex_distance_m": round(event["apex_distance_m"], 1),
                    "braking_distance_m": round(event["braking_distance_m"], 1),
                    "entry_speed_kph": round(event["entry_speed_kph"], 1),
                    "apex_speed_kph": round(event["apex_speed_kph"], 1),
                    "exit_speed_kph": _round_or_none(event.get("exit_speed_kph"), 1),
                    "speed_loss_kph": round(event["speed_loss_kph"], 1),
                    "brake_duration_ms": _round_or_none(event.get("brake_duration_ms"), 1),
                }
            )
        position_event = min(cluster, key=lambda row: abs(row["apex_distance_m"] - center))
        corners.append(
            {
                "corner_number": corner_number,
                "distance_m": round(center, 1),
                "x": _round_or_none(position_event.get("x"), 2),
                "y": _round_or_none(position_event.get("y"), 2),
                "drivers": driver_rows,
            }
        )
    if not corners:
        caveats.append("No braking events with a meaningful speed reduction were detected.")
    return {
        "session_id": session_id,
        "representative_laps": representatives,
        "corners": corners,
        "caveats": caveats,
    }


def calculate_car_performance(
    session_id: str,
    laps: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
) -> dict[str, Any]:
    representatives, samples = representative_telemetry_laps(laps, telemetry)
    team_by_driver = {
        str(driver.get("code") or "").upper(): str(driver.get("team", {}).get("name") or "Unknown")
        for driver in drivers
        if driver.get("code")
    }
    lap_by_driver = {row["driver_code"]: row["lap_number"] for row in representatives}
    driver_rows = []
    for driver, rows in sorted(samples.items()):
        speeds = [float(row["speed_kph"]) for row in rows if _number(row.get("speed_kph"))]
        if not speeds:
            continue
        throttle_samples = [
            value for row in rows if (value := _float(row.get("throttle_pct"))) is not None
        ]
        brake_samples = [
            value for row in rows if (value := _boolean(row.get("brake"))) is not None
        ]
        driver_rows.append(
            {
                "driver_code": driver,
                "team": team_by_driver.get(driver, "Unknown"),
                "lap_number": lap_by_driver.get(driver),
                "max_speed_kph": round(max(speeds), 1),
                "p95_speed_kph": round(_percentile(speeds, 0.95), 1),
                "low_speed_avg_kph": _bucket_average(speeds, 0, 150),
                "medium_speed_avg_kph": _bucket_average(speeds, 150, 250),
                "high_speed_avg_kph": _bucket_average(speeds, 250, math.inf),
                "full_throttle_pct": round(
                    100 * sum(value >= 98 for value in throttle_samples) / len(throttle_samples), 1
                )
                if throttle_samples
                else None,
                "braking_pct": round(
                    100 * sum(brake_samples) / len(brake_samples), 1
                )
                if brake_samples
                else None,
            }
        )

    teams = []
    team_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in driver_rows:
        team_groups[row["team"]].append(row)
    metric_names = [
        "max_speed_kph",
        "p95_speed_kph",
        "low_speed_avg_kph",
        "medium_speed_avg_kph",
        "high_speed_avg_kph",
        "full_throttle_pct",
        "braking_pct",
    ]
    for team, rows in sorted(team_groups.items()):
        aggregate: dict[str, Any] = {
            "team": team,
            "drivers": [row["driver_code"] for row in rows],
        }
        for field in metric_names:
            values = [float(row[field]) for row in rows if row.get(field) is not None]
            aggregate[field] = round(mean(values), 1) if values else None
        teams.append(aggregate)
    return {
        "session_id": session_id,
        "drivers": driver_rows,
        "teams": teams,
        "caveats": [
            "Profiles use each driver's fastest non-deleted lap with telemetry.",
            "Speed bands are sample averages: low <150, medium 150-250, high >=250 km/h.",
            "Maximum speed is telemetry-derived and may differ from the official speed trap.",
            "Throttle and braking percentages exclude samples where that channel is unavailable.",
        ],
    }


def calculate_pace_prediction(
    session_id: str,
    summary: dict[str, Any],
    laps: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
) -> dict[str, Any]:
    session_type = str(summary.get("session") or summary.get("type") or "Unknown")
    normalized = session_type.lower()
    is_practice = "practice" in normalized or normalized.startswith("fp") or "-fp" in session_id.lower()
    caveats = [
        "This is a relative long-run estimate, not an absolute race-time forecast.",
        "Unknown fuel loads, engine modes, setup programmes, traffic, and weather can dominate practice pace.",
        "Only clean stints with at least five timed laps are included; median pace limits outlier impact.",
    ]
    if not is_practice:
        return {
            "session_id": session_id,
            "available": False,
            "session_type": session_type,
            "drivers": [],
            "teams": [],
            "caveats": caveats + ["Pace prediction is only produced for practice sessions."],
        }

    clean = clean_laps(laps)
    team_by_driver = {
        str(driver.get("code") or "").upper(): str(driver.get("team", {}).get("name") or "Unknown")
        for driver in drivers
        if driver.get("code")
    }
    groups: dict[tuple[str, Any], list[dict[str, Any]]] = defaultdict(list)
    for lap in clean:
        groups[(str(lap.get("driver_code") or "").upper(), lap.get("stint"))].append(lap)

    runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (driver, stint), group in groups.items():
        times = [float(lap["lap_time_ms"]) for lap in group]
        filtered, _ = _filter_outliers(times)
        if not driver or len(filtered) < 5:
            continue
        runs[driver].append(
            {
                "stint": stint,
                "pace_ms": float(median(filtered)),
                "sample_count": len(filtered),
                "variability_ms": _robust_spread(filtered),
                "compounds": sorted({str(lap.get("compound")) for lap in group if lap.get("compound")}),
            }
        )

    rows = []
    for driver, driver_runs in sorted(runs.items()):
        sample_count = sum(run["sample_count"] for run in driver_runs)
        pace = sum(run["pace_ms"] * run["sample_count"] for run in driver_runs) / sample_count
        variability = sum(
            run["variability_ms"] * run["sample_count"] for run in driver_runs
        ) / sample_count
        confidence = "high" if sample_count >= 15 and len(driver_runs) >= 2 and variability < 1000 else (
            "medium" if sample_count >= 8 and variability < 1500 else "low"
        )
        rows.append(
            {
                "driver_code": driver,
                "team": team_by_driver.get(driver, "Unknown"),
                "estimated_race_pace_ms": round(pace, 1),
                "gap_to_best_ms": None,
                "sample_count": sample_count,
                "stint_count": len(driver_runs),
                "variability_ms": round(variability, 1),
                "confidence": confidence,
                "compounds": sorted(
                    {compound for run in driver_runs for compound in run["compounds"]}
                ),
            }
        )
    best = min((row["estimated_race_pace_ms"] for row in rows), default=None)
    for row in rows:
        row["gap_to_best_ms"] = (
            round(row["estimated_race_pace_ms"] - best, 1) if best is not None else None
        )
    rows.sort(key=lambda row: (row["gap_to_best_ms"] is None, row["gap_to_best_ms"] or 0))

    team_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        team_groups[row["team"]].append(row)
    teams = []
    for team, team_rows in sorted(team_groups.items()):
        total = sum(row["sample_count"] for row in team_rows)
        pace = sum(row["estimated_race_pace_ms"] * row["sample_count"] for row in team_rows) / total
        teams.append(
            {
                "team": team,
                "drivers": [row["driver_code"] for row in team_rows],
                "estimated_race_pace_ms": round(pace, 1),
                "gap_to_best_ms": None,
                "sample_count": total,
                "confidence": min(
                    (row["confidence"] for row in team_rows),
                    key=lambda value: {"low": 0, "medium": 1, "high": 2}[value],
                ),
            }
        )
    team_best = min((row["estimated_race_pace_ms"] for row in teams), default=None)
    for row in teams:
        row["gap_to_best_ms"] = (
            round(row["estimated_race_pace_ms"] - team_best, 1) if team_best is not None else None
        )
    teams.sort(key=lambda row: (row["gap_to_best_ms"] is None, row["gap_to_best_ms"] or 0))
    if not rows:
        caveats.append("No stint met the minimum five-clean-lap threshold.")
    return {
        "session_id": session_id,
        "available": bool(rows),
        "session_type": session_type,
        "drivers": rows,
        "teams": teams,
        "caveats": caveats,
    }


def calculate_fuel_adjusted_tyre_degradation(
    session_id: str,
    summary: dict[str, Any],
    laps: list[dict[str, Any]],
) -> dict[str, Any]:
    session_type = str(summary.get("session") or summary.get("type") or "Unknown")
    normalized = session_type.lower()
    if "race" in normalized or session_id.lower().endswith("-r"):
        fuel_correction = DEFAULT_RACE_FUEL_CORRECTION_MS_PER_LAP
    elif "sprint" in normalized or session_id.lower().endswith("-s"):
        fuel_correction = DEFAULT_SPRINT_FUEL_CORRECTION_MS_PER_LAP
    else:
        fuel_correction = 0.0

    rows = []
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for lap in clean_laps(laps):
        groups[(lap.get("driver_code"), lap.get("stint"), lap.get("compound"))].append(lap)
    for (driver, stint, compound), group in groups.items():
        samples = [
            (float(lap["tyre_age"]), float(lap["lap_time_ms"]))
            for lap in group
            if lap.get("tyre_age") is not None and lap.get("lap_time_ms") is not None
        ]
        base = {
            "driver_code": str(driver),
            "compound": str(compound),
            "stint": int(stint or 0),
            "sample_count": len(samples),
            "stint_length": len(group),
        }
        if len(samples) < 3 or len({sample[0] for sample in samples}) < 2:
            rows.append(
                {
                    **base,
                    "degradation_ms_per_lap": None,
                    "raw_slope_ms_per_lap": None,
                    "fuel_correction_ms_per_lap": fuel_correction,
                    "r_squared": None,
                    "excluded_outlier_count": 0,
                    "caveats": ["At least three clean laps at distinct tyre ages are required."],
                }
            )
            continue

        initial_slope = _theil_sen_slope(samples)
        intercept = median(y - initial_slope * x for x, y in samples)
        residuals = [y - (initial_slope * x + intercept) for x, y in samples]
        residual_center = median(residuals)
        residual_mad = median(abs(value - residual_center) for value in residuals)
        threshold = max(750.0, 3.5 * 1.4826 * residual_mad)
        inliers = [
            sample
            for sample, residual in zip(samples, residuals, strict=True)
            if abs(residual - residual_center) <= threshold
        ]
        if len(inliers) < 3 or len({sample[0] for sample in inliers}) < 2:
            inliers = samples
        slope, r_squared = _linear_fit(inliers)
        caveats = []
        if r_squared is not None and r_squared < 0.5:
            caveats.append("Low fit quality; treat the degradation estimate as directional only.")
        if fuel_correction == 0:
            caveats.append("No fuel correction is applied outside races because run fuel loads are unknown.")
        else:
            caveats.append(
                f"Includes an assumed {fuel_correction:.0f} ms/lap fuel-burn correction."
            )
        rows.append(
            {
                **base,
                "degradation_ms_per_lap": round(slope + fuel_correction, 2),
                "raw_slope_ms_per_lap": round(slope, 2),
                "fuel_correction_ms_per_lap": fuel_correction,
                "r_squared": round(r_squared, 3) if r_squared is not None else None,
                "excluded_outlier_count": len(samples) - len(inliers),
                "caveats": caveats,
            }
        )
    return {
        "session_id": session_id,
        "rows": rows,
        "model": {
            "method": "Theil-Sen residual filter followed by ordinary least squares",
            "race_fuel_correction_ms_per_lap": DEFAULT_RACE_FUEL_CORRECTION_MS_PER_LAP,
            "sprint_fuel_correction_ms_per_lap": DEFAULT_SPRINT_FUEL_CORRECTION_MS_PER_LAP,
        },
        "caveats": [
            "Fuel correction is an explicit generic assumption, not measured car fuel mass.",
            "Pit, deleted, inaccurate, neutralized, and statistical outlier laps are excluded.",
            "Track evolution, traffic, weather, and tyre management remain confounding factors.",
        ],
    }


def representative_telemetry_laps(
    laps: list[dict[str, Any]], telemetry: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    lap_meta = {
        (str(lap.get("driver_code") or "").upper(), int(lap.get("lap_number") or 0)): lap
        for lap in laps
        if lap.get("driver_code") and lap.get("lap_number")
    }
    grouped_samples: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in telemetry:
        driver = str(row.get("driver_code") or "").upper()
        lap_number = int(row.get("lap_number") or 0)
        if driver and lap_number > 0 and _number(row.get("distance_m")):
            grouped_samples[(driver, lap_number)].append(row)

    by_driver: dict[str, list[tuple[tuple[str, int], list[dict[str, Any]]]]] = defaultdict(list)
    for key, rows in grouped_samples.items():
        if len(rows) >= 3 and not lap_meta.get(key, {}).get("is_deleted"):
            by_driver[key[0]].append((key, rows))

    representatives = []
    selected: dict[str, list[dict[str, Any]]] = {}
    for driver, candidates in sorted(by_driver.items()):
        key, rows = min(
            candidates,
            key=lambda item: (
                lap_meta.get(item[0], {}).get("lap_time_ms") is None,
                lap_meta.get(item[0], {}).get("lap_time_ms") or math.inf,
                item[0][1],
            ),
        )
        prepared = _prepare_samples(rows)
        if len(prepared) < 3 or prepared[-1]["distance_m"] <= 0:
            continue
        selected[driver] = prepared
        representatives.append(
            {
                "driver_code": driver,
                "lap_number": key[1],
                "lap_time_ms": lap_meta.get(key, {}).get("lap_time_ms"),
            }
        )
    return representatives, selected


def _prepare_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: float(row.get("distance_m") or 0))
    deduped: list[dict[str, Any]] = []
    seen_distances: set[float] = set()
    for raw in ordered:
        distance = float(raw.get("distance_m") or 0)
        if distance in seen_distances:
            continue
        seen_distances.add(distance)
        deduped.append({**raw, "distance_m": distance})
    elapsed_values = [_float(row.get("relative_time_ms")) for row in deduped]
    if sum(value is not None for value in elapsed_values) >= 2:
        origin = next(value for value in elapsed_values if value is not None)
        for row, value in zip(deduped, elapsed_values, strict=True):
            row["_elapsed_ms"] = value - origin if value is not None else None
    else:
        elapsed = 0.0
        for index, row in enumerate(deduped):
            if index:
                previous = deduped[index - 1]
                distance_delta = row["distance_m"] - previous["distance_m"]
                speeds = [
                    value
                    for value in [_float(previous.get("speed_kph")), _float(row.get("speed_kph"))]
                    if value and value > 0
                ]
                if speeds:
                    elapsed += distance_delta / (mean(speeds) / 3.6) * 1000
            row["_elapsed_ms"] = elapsed
    return [row for row in deduped if row.get("_elapsed_ms") is not None]


def _braking_events(driver: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[tuple[int, int]] = []
    start = None
    for index, row in enumerate(rows):
        braking = bool(row.get("brake"))
        if braking and start is None:
            start = index
        elif not braking and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(rows) - 1))

    merged: list[tuple[int, int]] = []
    for run in runs:
        if merged and rows[run[0]]["distance_m"] - rows[merged[-1][1]]["distance_m"] <= 80:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)

    events = []
    for start_index, end_index in merged:
        start_distance = rows[start_index]["distance_m"]
        search_end = rows[end_index]["distance_m"] + 250
        window = [
            row
            for row in rows[start_index:]
            if row["distance_m"] <= search_end and _number(row.get("speed_kph"))
        ]
        if not window or not _number(rows[start_index].get("speed_kph")):
            continue
        apex = min(window, key=lambda row: float(row["speed_kph"]))
        entry_speed = float(rows[start_index]["speed_kph"])
        apex_speed = float(apex["speed_kph"])
        braking_distance = float(apex["distance_m"] - start_distance)
        if entry_speed - apex_speed < 8 or braking_distance < 5:
            continue
        exit_speed = _interpolate(rows, min(rows[-1]["distance_m"], apex["distance_m"] + 150), "speed_kph")
        start_time = _interpolate(rows, start_distance, "_elapsed_ms")
        end_time = _interpolate(rows, rows[end_index]["distance_m"], "_elapsed_ms")
        events.append(
            {
                "driver_code": driver,
                "brake_start_m": start_distance,
                "apex_distance_m": float(apex["distance_m"]),
                "braking_distance_m": braking_distance,
                "entry_speed_kph": entry_speed,
                "apex_speed_kph": apex_speed,
                "exit_speed_kph": exit_speed,
                "speed_loss_kph": entry_speed - apex_speed,
                "brake_duration_ms": end_time - start_time
                if end_time is not None and start_time is not None
                else None,
                "x": _float(apex.get("x")),
                "y": _float(apex.get("y")),
            }
        )
    return events


def _interpolate(rows: list[dict[str, Any]], distance: float, field: str) -> float | None:
    if not rows:
        return None
    if distance <= rows[0]["distance_m"]:
        return _float(rows[0].get(field))
    if distance >= rows[-1]["distance_m"]:
        return _float(rows[-1].get(field))
    for index in range(1, len(rows)):
        right = rows[index]
        if right["distance_m"] < distance:
            continue
        left = rows[index - 1]
        left_value = _float(left.get(field))
        right_value = _float(right.get(field))
        if left_value is None or right_value is None:
            return left_value if left_value is not None else right_value
        span = right["distance_m"] - left["distance_m"]
        ratio = (distance - left["distance_m"]) / span if span else 0
        return left_value + (right_value - left_value) * ratio
    return None


def _filter_outliers(values: list[float]) -> tuple[list[float], int]:
    if len(values) < 4:
        return values, 0
    center = median(values)
    mad = median(abs(value - center) for value in values)
    threshold = max(750.0, 3.5 * 1.4826 * mad)
    filtered = [value for value in values if abs(value - center) <= threshold]
    return (filtered or values), len(values) - len(filtered)


def _robust_spread(values: list[float]) -> float:
    center = median(values)
    return float(1.4826 * median(abs(value - center) for value in values))


def _theil_sen_slope(samples: list[tuple[float, float]]) -> float:
    slopes = [
        (right_y - left_y) / (right_x - left_x)
        for index, (left_x, left_y) in enumerate(samples)
        for right_x, right_y in samples[index + 1 :]
        if right_x != left_x
    ]
    return float(median(slopes)) if slopes else 0.0


def _linear_fit(samples: list[tuple[float, float]]) -> tuple[float, float | None]:
    x_values = [sample[0] for sample in samples]
    y_values = [sample[1] for sample in samples]
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    slope = (
        sum((x - x_mean) * (y - y_mean) for x, y in samples) / denominator
        if denominator
        else 0.0
    )
    intercept = y_mean - slope * x_mean
    fitted = [slope * x + intercept for x in x_values]
    residual = sum((y - fit) ** 2 for y, fit in zip(y_values, fitted, strict=True))
    total = sum((y - y_mean) ** 2 for y in y_values)
    return float(slope), float(1 - residual / total) if total else None


def _bucket_average(values: list[float], minimum: float, maximum: float) -> float | None:
    selected = [value for value in values if minimum <= value < maximum]
    return round(mean(selected), 1) if selected else None


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _number(value: Any) -> bool:
    return _float(value) is not None


def _float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _round_or_none(value: Any, digits: int) -> float | None:
    number = _float(value)
    return round(number, digits) if number is not None else None


def _boolean(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    number = _float(value)
    if number is not None:
        return bool(number)
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "on"}:
        return True
    if normalized in {"false", "no", "off"}:
        return False
    return None
