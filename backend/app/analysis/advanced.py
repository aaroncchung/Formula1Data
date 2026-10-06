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

from .common import clean_laps, lap_number


DEFAULT_MINISECTOR_COUNT = 25
DEFAULT_RACE_FUEL_CORRECTION_MS_PER_LAP = 55.0
DEFAULT_SPRINT_FUEL_CORRECTION_MS_PER_LAP = 35.0

# Session types, as FastF1 names them and as the session code, that are run on
# a race fuel load. "Sprint Qualifying" and "Sprint Shootout" are not.
RACE_SESSION_TYPES = {"race", "r"}
SPRINT_SESSION_TYPES = {"sprint", "s"}

# A lap's telemetry is complete when it runs from line to line: its clock
# matches the timed lap and its distance matches a normal lap. On the 2026
# Austrian GP all 1,149 clean laps match their lap time to the millisecond and
# measure 97.6% to 101.5% of the median lap; lap 1 measures 101.7% to 105.9%.
TELEMETRY_LAP_TIME_TOLERANCE = 0.02
TELEMETRY_LAP_DISTANCE_TOLERANCE = 0.03
# How far the nearest sample may be from a minisector boundary. Laps arrive
# with holes of a second or more (the widest in a clean lap of that race is
# 141 m), and a boundary time interpolated across one depends on the guess
# made about the speed in between. Within 20 m of a sample two reasonable
# guesses (constant speed, constant acceleration) agree to a median of under
# 2 ms; beyond it they differ by 5 to 10 ms at the median and up to 82 ms,
# against a typical winning margin of about 25 ms. 0.9% of boundaries are
# further than that.
MAX_BOUNDARY_SAMPLE_DISTANCE_M = 20.0

# A degradation fit needs enough laps for its own quality figure to mean
# something: with fewer than eight, the residual spread rests on under six
# degrees of freedom.
MIN_DEGRADATION_LAPS = 8
# A rate is reported when the fitted slope is pinned down, which is judged by
# its standard error: at most 20 ms/lap, or at most a quarter of the slope
# itself. At 20 ms/lap the 95% interval is about +/-40 ms/lap, the size of a
# typical slope (the median in the 2026 Austrian GP is about 45 ms/lap); past
# that the figure cannot tell a tyre that is wearing from one that is not. The
# relative limit keeps short, steep stints, whose slope is uncertain in ms but
# not in doubt: Leclerc's opening stint in that race is 156 +/- 25 ms/lap. Of
# its 60 fits with enough laps, 47 pass the first limit and 5 more the second.
MAX_SLOPE_STANDARD_ERROR_MS_PER_LAP = 20.0
MAX_SLOPE_RELATIVE_STANDARD_ERROR = 0.25


def calculate_track_dominance(
    session_id: str,
    laps: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
    minisector_count: int = DEFAULT_MINISECTOR_COUNT,
) -> dict[str, Any]:
    representatives, samples, left_out = fastest_complete_telemetry_laps(laps, telemetry)
    result: dict[str, Any] = {
        "session_id": session_id,
        "representative_laps": representatives,
        "excluded_drivers": left_out,
        "minisector_count": 0,
        "minisectors": [],
    }
    caveats = [
        "Each driver's fastest clean lap with complete telemetry is compared: accurate, not "
        "deleted, not a pit lap, not lap 1 and not run under a safety car, VSC or red flag.",
        "Minisector time is interpolated at distance boundaries; it is not an FIA timing sector.",
        "Each lap's distance is scaled to a common lap length, so a boundary sits at the same "
        "share of every lap. Distance is integrated from speed, so the same corner can still "
        "sit several metres apart between two laps, and through a slow corner that moves "
        "tenths of a second between neighbouring minisectors.",
        "A driver has no time in a minisector where their telemetry has no sample within "
        f"{MAX_BOUNDARY_SAMPLE_DISTANCE_M:.0f} m of one of its boundaries.",
    ]
    if not samples:
        return {**result, "caveats": caveats + ["No usable telemetry laps were available."]}
    if left_out:
        caveats.append(f"Left out, having no such lap: {', '.join(left_out)}.")

    # Each lap's distance is its own integral of speed, and those integrals
    # disagree: the 21 representative laps of the 2026 Austrian GP measure
    # 4,274 to 4,311 m for the same 4,318 m of track. Cutting every lap at the
    # shortest one's length compared different places and dropped the end of
    # the longer laps (444 ms of Alonso's). Placing boundaries at the same
    # share of each lap makes a driver's minisectors sum to the lap, and took
    # the largest winning margin in that race from 485 ms to 280 ms.
    reference_length = float(median(_lap_length(rows) for rows in samples.values()))
    if reference_length <= 0:
        return {
            **result,
            "caveats": caveats + ["Telemetry did not contain a usable distance axis."],
        }

    count = max(1, min(int(minisector_count), int(reference_length // 100) or 1))
    reference_driver = min(
        representatives,
        key=lambda row: (row.get("lap_time_ms") is None, row.get("lap_time_ms") or math.inf),
    )["driver_code"]
    reference = samples[reference_driver]
    sectors = []
    for index in range(count):
        start_share = index / count
        end_share = (index + 1) / count
        driver_times: dict[str, float] = {}
        for driver, rows in samples.items():
            start_time = _boundary_time(rows, start_share)
            end_time = _boundary_time(rows, end_share)
            if start_time is None or end_time is None or end_time < start_time:
                continue
            driver_times[driver] = round(end_time - start_time, 1)

        ordered = sorted(driver_times.items(), key=lambda item: (item[1], item[0]))
        winner = ordered[0] if ordered else (None, None)
        midpoint = _distance_at(reference, (start_share + end_share) / 2)
        sectors.append(
            {
                "index": index + 1,
                "start_distance_m": round(reference_length * start_share, 1),
                "end_distance_m": round(reference_length * end_share, 1),
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
        **result,
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
    fuel_correction = _fuel_correction(summary, session_id)

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
        # Every row carries every field; a fit that is not reported keeps its
        # rate fields empty and says why in ``fit_status`` and ``caveats``.
        row: dict[str, Any] = {
            "driver_code": str(driver),
            "compound": str(compound),
            "stint": int(stint or 0),
            "sample_count": len(samples),
            "stint_length": len(group),
            "degradation_ms_per_lap": None,
            "raw_slope_ms_per_lap": None,
            "fuel_correction_ms_per_lap": fuel_correction,
            "r_squared": None,
            "residual_spread_ms": None,
            "slope_standard_error_ms_per_lap": None,
            "excluded_outlier_count": 0,
        }
        if len(samples) < MIN_DEGRADATION_LAPS:
            rows.append(
                {
                    **row,
                    "fit_status": "too_few_laps",
                    "caveats": [
                        f"No rate reported: {len(samples)} clean laps, and at least "
                        f"{MIN_DEGRADATION_LAPS} are required."
                    ],
                }
            )
            continue

        inliers = _without_residual_outliers(samples)
        excluded = len(samples) - len(inliers)
        row["excluded_outlier_count"] = excluded
        # Laps that share a tyre age say nothing about the slope between them.
        usable = min(len(inliers), len({age for age, _ in inliers}))
        if usable < MIN_DEGRADATION_LAPS:
            rows.append(
                {
                    **row,
                    "fit_status": "too_few_laps",
                    "caveats": [
                        f"No rate reported: {usable} laps at distinct tyre ages remain after "
                        f"excluding {excluded} as outliers, and at least "
                        f"{MIN_DEGRADATION_LAPS} are required."
                    ],
                }
            )
            continue

        slope, r_squared, residual_spread, slope_error = _linear_fit(inliers)
        row.update(
            {
                "r_squared": _round_or_none(r_squared, 3),
                "residual_spread_ms": _round_or_none(residual_spread, 1),
                "slope_standard_error_ms_per_lap": _round_or_none(slope_error, 2),
            }
        )
        slope_error_limit = max(
            MAX_SLOPE_STANDARD_ERROR_MS_PER_LAP, MAX_SLOPE_RELATIVE_STANDARD_ERROR * abs(slope)
        )
        if slope_error is None or slope_error > slope_error_limit:
            rows.append(
                {
                    **row,
                    "fit_status": "poor_fit",
                    "caveats": [
                        "No rate reported: the lap times scatter too much to fix the slope. "
                        f"Its standard error is {_float(slope_error, math.inf):.0f} ms/lap, "
                        f"over the limit of {MAX_SLOPE_STANDARD_ERROR_MS_PER_LAP:.0f} ms/lap "
                        f"or {MAX_SLOPE_RELATIVE_STANDARD_ERROR:.0%} of the slope."
                    ],
                }
            )
            continue

        degradation = slope + fuel_correction
        caveats = []
        if fuel_correction == 0:
            caveats.append("No fuel correction is applied outside races because run fuel loads are unknown.")
        else:
            caveats.append(
                f"Includes an assumed {fuel_correction:.0f} ms/lap fuel-burn correction."
            )
        if degradation < 0:
            caveats.append(
                "A negative rate means lap times fell through the stint for a reason other "
                "than the tyres (clearing traffic, track evolution, tyre management)."
            )
        rows.append(
            {
                **row,
                "degradation_ms_per_lap": round(degradation, 2),
                "raw_slope_ms_per_lap": round(slope, 2),
                "fit_status": "ok",
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
            "minimum_laps": MIN_DEGRADATION_LAPS,
            "max_slope_standard_error_ms_per_lap": MAX_SLOPE_STANDARD_ERROR_MS_PER_LAP,
            "max_slope_relative_standard_error": MAX_SLOPE_RELATIVE_STANDARD_ERROR,
        },
        "caveats": [
            "Fuel correction is an explicit generic assumption, not measured car fuel mass.",
            "Pit, deleted, inaccurate, neutralized, and statistical outlier laps are excluded.",
            "Track evolution, traffic, weather, and tyre management remain confounding factors.",
            f"A rate is reported only for a stint with at least {MIN_DEGRADATION_LAPS} clean "
            "laps whose fitted slope has a standard error of at most "
            f"{MAX_SLOPE_STANDARD_ERROR_MS_PER_LAP:.0f} ms/lap or "
            f"{MAX_SLOPE_RELATIVE_STANDARD_ERROR:.0%} of the slope. R² is shown but does not "
            "decide this: a tyre that barely degrades has an R² near zero however clean the "
            "stint.",
        ],
    }


def _fuel_correction(summary: dict[str, Any], session_id: str) -> float:
    """Fuel-burn correction for the session, matched on its exact type.

    This used to test whether the name contained "sprint", which is also true
    of "Sprint Qualifying" and "Sprint Shootout": qualifying sessions, run on
    a few laps of fuel, were given the 35 ms/lap sprint-race correction.
    """
    session_type = str(summary.get("session") or summary.get("type") or "").strip().lower()
    if session_type in ("", "unknown"):
        # The API calls this with an empty summary. The last part of a session
        # id is the session code ("2026-08-r", "2026-08-sq"), matched whole.
        session_type = session_id.strip().lower().rsplit("-", 1)[-1]
    if session_type in RACE_SESSION_TYPES:
        return DEFAULT_RACE_FUEL_CORRECTION_MS_PER_LAP
    if session_type in SPRINT_SESSION_TYPES:
        return DEFAULT_SPRINT_FUEL_CORRECTION_MS_PER_LAP
    return 0.0


def _without_residual_outliers(samples: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop laps far from a robust first fit, so one slow lap cannot tilt the line."""
    initial_slope = _theil_sen_slope(samples)
    intercept = median(y - initial_slope * x for x, y in samples)
    residuals = [y - (initial_slope * x + intercept) for x, y in samples]
    residual_center = median(residuals)
    residual_mad = median(abs(value - residual_center) for value in residuals)
    threshold = max(750.0, 3.5 * 1.4826 * residual_mad)
    return [
        sample
        for sample, residual in zip(samples, residuals, strict=True)
        if abs(residual - residual_center) <= threshold
    ]


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


def fastest_complete_telemetry_laps(
    laps: list[dict[str, Any]], telemetry: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[str]]:
    """Pick each driver's fastest clean lap whose telemetry runs line to line.

    ``representative_telemetry_laps`` takes the fastest non-deleted lap that
    has any telemetry, which for a driver who retires early is whatever they
    managed. In the 2026 Austrian GP Bottas completed lap 1 and an in-lap, so
    his lap 1 (84.016 s) was compared with flying laps of 70 to 74 s and won
    6 of 25 minisectors. Its telemetry measures 4,495 m against 4,287 m for a
    normal lap, so his distance axis was up to 208 m, more than a minisector,
    out of step: his straights were timed against everyone else's corners.

    Here a lap must pass ``clean_laps`` (accurate, not deleted, not a pit lap,
    not lap 1, not neutralised) and its telemetry must be complete. A driver
    with no such lap is left out and named in the third return value. Yellow
    flags are allowed: the status is session-wide, and a lap that is still the
    driver's fastest was evidently not slowed by one.
    """
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in telemetry:
        driver = str(row.get("driver_code") or "").upper()
        number = lap_number(row) or 0
        if driver and number > 0 and _number(row.get("distance_m")):
            grouped[(driver, number)].append(row)

    drivers = {key[0] for key in grouped}
    drivers.update(str(lap["driver_code"]).upper() for lap in laps if lap.get("driver_code"))

    # (lap time, lap number, lap) per driver: sorts fastest first, earliest on a tie.
    candidates: dict[str, list[tuple[float, int, dict[str, Any]]]] = defaultdict(list)
    ends = []
    for lap in clean_laps(laps):
        driver = str(lap.get("driver_code") or "").upper()
        number = lap_number(lap) or 0
        lap_time = _float(lap.get("lap_time_ms"))
        rows = grouped.get((driver, number))
        if not rows or lap_time is None:
            continue
        candidates[driver].append((lap_time, number, lap))
        ends.append(max(float(row["distance_m"]) for row in rows))
    # The length of a normal lap is not an input, so take it from the laps
    # themselves: most clean laps are complete, and the median ignores the rest.
    usual_end = float(median(ends)) if ends else 0.0

    representatives = []
    selected: dict[str, list[dict[str, Any]]] = {}
    for driver, driver_laps in sorted(candidates.items()):
        for lap_time, number, lap in sorted(driver_laps, key=lambda item: item[:2]):
            rows = _prepare_samples(grouped[(driver, number)])
            if not _covers_lap(rows, lap_time, usual_end):
                continue
            selected[driver] = rows
            representatives.append(
                {"driver_code": driver, "lap_number": number, "lap_time_ms": lap["lap_time_ms"]}
            )
            break
    return representatives, selected, sorted(drivers - set(selected))


def _covers_lap(rows: list[dict[str, Any]], lap_time_ms: float, usual_end: float) -> bool:
    """True when prepared telemetry runs the whole lap, in distance and on the clock."""
    if len(rows) < 3 or usual_end <= 0 or lap_time_ms <= 0:
        return False
    slack = TELEMETRY_LAP_DISTANCE_TOLERANCE * usual_end
    if rows[0]["distance_m"] > slack or abs(rows[-1]["distance_m"] - usual_end) > slack:
        return False
    if any(_float(row.get("relative_time_ms")) is None for row in (rows[0], rows[-1])):
        # No clock was recorded and ``_prepare_samples`` rebuilt one from
        # speed and distance; that is the same information as the distance
        # check, so there is nothing independent to compare.
        return True
    elapsed = rows[-1]["_elapsed_ms"] - rows[0]["_elapsed_ms"]
    return abs(elapsed - lap_time_ms) <= TELEMETRY_LAP_TIME_TOLERANCE * lap_time_ms


def _lap_length(rows: list[dict[str, Any]]) -> float:
    return float(rows[-1]["distance_m"] - rows[0]["distance_m"])


def _distance_at(rows: list[dict[str, Any]], share: float) -> float:
    """The lap's own distance at a share (0 to 1) of the way round it."""
    first, last = rows[0]["distance_m"], rows[-1]["distance_m"]
    return min(max(first + share * (last - first), first), last)


def _boundary_time(rows: list[dict[str, Any]], share: float) -> float | None:
    """Elapsed time at a share of the lap, or None where the lap has a hole there.

    ``_interpolate`` always answers: it draws a straight line across any gap
    and clamps beyond the ends, so a lap that never sampled a stretch of track
    still gets a time for it and can win the minisector.
    """
    distance = _distance_at(rows, share)
    for index in range(1, len(rows)):
        right = rows[index]
        if right["distance_m"] < distance:
            continue
        left = rows[index - 1]
        nearest = min(distance - left["distance_m"], right["distance_m"] - distance)
        if nearest > MAX_BOUNDARY_SAMPLE_DISTANCE_M:
            return None
        span = right["distance_m"] - left["distance_m"]
        ratio = (distance - left["distance_m"]) / span if span else 0.0
        return left["_elapsed_ms"] + (right["_elapsed_ms"] - left["_elapsed_ms"]) * ratio
    return None


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


def _linear_fit(
    samples: list[tuple[float, float]],
) -> tuple[float, float | None, float | None, float | None]:
    """Least-squares line: slope, R², residual spread and the slope's standard error.

    The standard error is the fit-quality figure that decides whether a rate
    is reported. R² cannot do that job: it measures how much of the variation
    the slope explains, so a stint with almost no degradation scores near zero
    however tightly its laps sit on the line. In the 2026 Austrian GP
    Hulkenberg's second stint is among the cleanest in the race (19 laps, 197 ms
    residual spread, slope standard error 8 ms/lap) and has an R² of 0.08.
    """
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
    r_squared = float(1 - residual / total) if total else None
    # Two parameters are fitted, so the spread has n - 2 degrees of freedom.
    freedom = len(samples) - 2
    residual_spread = math.sqrt(residual / freedom) if freedom > 0 else None
    slope_error = (
        residual_spread / math.sqrt(denominator)
        if residual_spread is not None and denominator
        else None
    )
    return float(slope), r_squared, residual_spread, slope_error


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
