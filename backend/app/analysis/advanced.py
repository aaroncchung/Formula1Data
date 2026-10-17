"""Pure-Python telemetry analyses shared by the API and static artifact pipeline.

The functions in this module deliberately return plain dictionaries.  They avoid
runtime-only dependencies so the static pipeline can use the exact same methods as
the optional FastAPI service.
"""

from __future__ import annotations

from bisect import bisect_left
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

# An official corner is found on a lap by position: the lap's sample nearest
# the corner's coordinates. Where the corner's distance along the lap is known
# as well, only samples within this far of it are considered, so that a stretch
# of track that passes close by (the two sides of a hairpin, a crossover) is
# never taken for the corner. Laps disagree about distance by about 1%, which
# on the longest circuit is 70 m.
OFFICIAL_CORNER_SEARCH_M = 200.0
# And the sample has to be at the corner. The corners of the 2026 circuits lie
# within 20 m of the line a fast lap takes, so a lap whose samples never come
# this near one did not go through it: it stopped before the corner, or its
# position data did.
#
# Where the two limits disagree, the line is believed. Every lap compared was
# timed and its telemetry runs the length of that time, so it went all the way
# round, and a sample at a corner is that corner even where the lap's distance
# says otherwise: in the 2026 Chinese sprint F1's car feed repeats itself for
# seconds at a time on eight drivers' fastest laps, whose speed then measures
# the lap from 8% short to 15% long.
OFFICIAL_CORNER_REACH_M = 50.0
# A lap's line runs from one positioned sample to the next. Two further apart
# than this on the ground have a hole between them, and the line is not drawn
# across it. The position feed can miss a second or so, which at speed is
# 100 m.
OFFICIAL_CORNER_LINE_STEP_M = 150.0
# ``x`` and ``y`` are F1's position data, which is in tenths of a metre.
POSITION_UNITS_PER_METRE = 10.0
# A driver who does not brake for a corner still has a slowest point near it.
# It is looked for this far either side of the corner, and never past the
# midpoint to the next one.
OFFICIAL_CORNER_WINDOW_M = 75.0
# The brake coming off and going on again is one braking when it goes on
# within this far of where it came off.
SAME_BRAKING_GAP_M = 80.0
# A braking is counted when it takes this much off the car, over this far.
MIN_BRAKING_SPEED_LOSS_KPH = 8.0
MIN_BRAKING_DISTANCE_M = 5.0
# Its slowest point is looked for no further than this past where the brake came off.
BRAKING_REACH_M = 250.0


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
    if all(sector["midpoint"]["x"] is None for sector in sectors):
        caveats.append(
            "The quickest lap has no position data, so the minisectors cannot be placed on a map."
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
    telemetry: Any,
    corners: list[dict[str, Any]] | None = None,
    reference_lap_length_m: float | None = None,
) -> dict[str, Any]:
    """Braking and speed through each corner, on each driver's fastest lap.

    ``corners`` are the circuit's official corner positions: ``number``,
    ``letter``, ``x``, ``y`` and, where it is known, ``distance_m`` along the
    lap, measured on a lap ``reference_lap_length_m`` long. With them the laps
    are segmented by the real corners, and the result says so in
    ``corner_source``. Without them, or when none can be found on any lap,
    corners are inferred from where the drivers brake, as before (AR-17).

    A driver's lap is their fastest clean lap whose telemetry runs the length
    of its lap time (``fastest_complete_telemetry_laps``, by the clock alone:
    a corner is found by position, and a lap that ran its time went all the
    way round whatever its distance says). It used to be their fastest lap
    with any telemetry, and for a driver out early that is what they managed:
    in the 2026 Monaco GP Verstappen's only lap, lap 1, which has no lap time
    and stops at the chicane, and in the 2026 Austrian GP Bottas's lap 1, a
    standing start counted from the grid. Such a driver is left out, and the
    result names them.
    """
    by_lap = telemetry_by_lap(telemetry, lambda row: lap_number(row) or 0)
    representatives, samples, left_out = fastest_complete_telemetry_laps(laps, by_lap, by_distance=False)
    compared = [
        "Each driver's fastest clean lap whose telemetry runs the length of its lap time is compared: "
        "accurate, not deleted, not a pit lap, not lap 1 and not run under a safety car, VSC or red flag.",
    ]
    if left_out:
        compared.append(f"Left out, having no such lap: {', '.join(left_out)}.")
    placed = _official_corner_rows(_usable_corners(corners), samples, reference_lap_length_m)
    if placed is not None:
        official, not_passed = placed
        caveats = [
            "Corners are the circuit's official corner positions. Each is found on a driver's "
            "lap by position, so a distance shown for a driver is along that driver's own lap.",
            "A corner's stretch of a lap runs from half-way back to the corner before it to half-way "
            "on to the next. A braking is a corner's when the car is still slowing from it in that "
            f"stretch: before it has gathered {MIN_BRAKING_SPEED_LOSS_KPH:.0f} km/h from the slowest it "
            f"has been, before the next braking begins, and within {BRAKING_REACH_M:.0f} m of where the "
            "brake came off. The slowest point given is the slowest in the corner's stretch while it "
            "is, and of more than one braking the one whose slowest point is nearest the corner is "
            "given. So a braking that goes on through two corners' stretches is given for both, from "
            "the one brake point, and one that begins past a corner, in its stretch, is given for it.",
            f"The brake coming off and going on again within {SAME_BRAKING_GAP_M:.0f} m, without the car "
            f"gaining {MIN_BRAKING_SPEED_LOSS_KPH:.0f} km/h, is one braking. A braking is not counted for "
            f"a corner unless it has taken {MIN_BRAKING_SPEED_LOSS_KPH:.0f} km/h off the car by the "
            "corner's slowest point. Where the driver did not brake for a corner, only the slowest speed "
            f"within {OFFICIAL_CORNER_WINDOW_M:.0f} m of it, before the brake next goes on past it, and "
            "the exit speed are given.",
            "Entry, apex, and exit values are interpolated by distance between telemetry samples.",
            *compared,
        ]
        unplaced = sorted(driver for driver, rows in samples.items() if not _has_position(rows))
        if unplaced:
            caveats.append(
                f"No position data on the lap of: {', '.join(unplaced)}. Their corners are found by "
                "distance along the lap, which can be tens of metres out."
            )
        if not_passed:
            # A whole lap can still miss a corner: one that leaves the track,
            # or whose position feed freezes. Its rows for those corners are
            # not there, and why is said.
            caveats.append(
                "Not seen at a corner on the lap compared: "
                + "; ".join(f"{driver} at turn {', '.join(turns)}" for driver, turns in sorted(not_passed.items()))
                + f". The lap's position data does not come within {OFFICIAL_CORNER_REACH_M:.0f} m of the "
                "corner, so the driver has no figures for it."
            )
        caveats.extend(_brake_unread_caveat(official))
        return {
            "session_id": session_id,
            "corner_source": "official",
            "representative_laps": representatives,
            "corners": official,
            "caveats": caveats,
        }

    caveats = [
        "Corners are inferred from brake application and speed loss, not official circuit geometry.",
        "Entry, apex, and exit values are interpolated by distance between telemetry samples.",
        *compared,
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

    inferred = []
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
            # A corner found from the braking is, on a driver's lap, where that driver was slowest.
            driver_rows.append(_corner_driver_row(driver, event, event["apex_distance_m"]))
        position_event = min(cluster, key=lambda row: abs(row["apex_distance_m"] - center))
        inferred.append(
            {
                "corner_number": corner_number,
                "letter": None,
                "distance_m": round(center, 1),
                "x": _round_or_none(position_event.get("x"), 2),
                "y": _round_or_none(position_event.get("y"), 2),
                "drivers": driver_rows,
            }
        )
    if not inferred:
        caveats.append("No braking events with a meaningful speed reduction were detected.")
    elif all(corner["x"] is None for corner in inferred):
        caveats.append(
            "The laps compared have no position data, so the corners cannot be placed on a map."
        )
    elif unplaced := sum(corner["x"] is None for corner in inferred):
        # One lap with positions for part of its length places the corners it
        # reached: in the 2026 Monaco race, built without its circuit file,
        # that is one corner of nine, and nothing was said of the other eight.
        caveats.append(
            f"{unplaced} of the {len(inferred)} corners cannot be placed on a map: the laps compared "
            "have no position data there."
        )
    caveats.extend(_brake_unread_caveat(inferred))
    return {
        "session_id": session_id,
        "corner_source": "inferred",
        "representative_laps": representatives,
        "corners": inferred,
        "caveats": caveats,
    }


def _brake_unread_caveat(corners: list[dict[str, Any]]) -> list[str]:
    """What to say of the corners whose braking F1's feed does not show whole, or nothing when it shows every one.

    Two different things, said apart. A driver seen braking from the sample
    the reading comes back on did brake, from somewhere before it, and so did
    one slowed by a brake that reads on from where the car was still
    gathering speed. A driver not seen braking at all, with part of the
    approach unread, may have or may not.
    """

    def drivers(kind: str) -> str:
        return ", ".join(
            sorted({row["driver_code"] for corner in corners for row in corner["drivers"] if row["braking"] == kind})
        )

    caveats = []
    if began := drivers("began_unread"):
        caveats.append(
            "F1's car feed has no brake reading where the braking for a corner began, or has the brake "
            f"on there while the car gathers speed, for: {began}. The driver braked, from a point that is "
            "not known: the brake point and what is counted from it are left out."
        )
    if unread := drivers("unread"):
        caveats.append(
            f"F1's car feed has no brake reading on part of the approach to a corner, and shows no "
            f"braking for it, for: {unread}. Whether the driver braked there is not known, which is not "
            "a driver who did not brake."
        )
    return caveats


def _has_position(rows: list[dict[str, Any]]) -> bool:
    return any(_number(row.get("x")) and _number(row.get("y")) for row in rows)


def _corner_driver_row(driver: str, event: dict[str, Any], corner_distance: float) -> dict[str, Any]:
    return {
        "driver_code": driver,
        "corner_distance_m": round(corner_distance, 1),
        "brake_start_m": _round_or_none(event.get("brake_start_m"), 1),
        "apex_distance_m": round(event["apex_distance_m"], 1),
        "braking_distance_m": _round_or_none(event.get("braking_distance_m"), 1),
        "entry_speed_kph": _round_or_none(event.get("entry_speed_kph"), 1),
        "apex_speed_kph": round(event["apex_speed_kph"], 1),
        "exit_speed_kph": _round_or_none(event.get("exit_speed_kph"), 1),
        "speed_loss_kph": _round_or_none(event.get("speed_loss_kph"), 1),
        "brake_duration_ms": _round_or_none(event.get("brake_duration_ms"), 1),
        "braking": event["braking"],
    }


def _usable_corners(corners: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Official corners that have a number and something to find them by."""
    usable = []
    for corner in corners or []:
        number = _float(corner.get("number"))
        x, y, distance = _float(corner.get("x")), _float(corner.get("y")), _float(corner.get("distance_m"))
        if number is None or ((x is None or y is None) and distance is None):
            continue
        usable.append(
            {
                "number": int(number),
                "letter": str(corner.get("letter") or "").strip() or None,
                "x": x,
                "y": y,
                "distance_m": distance,
            }
        )
    return usable


def _official_corner_rows(
    corners: list[dict[str, Any]],
    samples: dict[str, list[dict[str, Any]]],
    reference_lap_length_m: float | None,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]] | None:
    """Each official corner with every driver's figures for it, or None if no lap can place one.

    With them, by driver, the corners a lap is not seen to pass. Every lap
    is one that went all the way round.
    """
    if not corners:
        return None
    by_corner: list[dict[str, dict[str, Any]]] = [{} for _ in corners]
    placed_at: list[list[float]] = [[] for _ in corners]
    not_passed: dict[str, list[str]] = {}
    for driver, rows in sorted(samples.items()):
        # The official distances are along a lap of the reference length, and
        # are scaled to this lap's.
        length = _lap_length(rows)
        scale = length / reference_lap_length_m if reference_lap_length_m and length > 0 else 1.0
        distances = _corners_on_lap(rows, corners, scale)
        found = [(distance, index) for index, distance in enumerate(distances) if distance is not None]
        if len(found) < len(corners):
            not_passed[driver] = [
                f"{corner['number']}{corner['letter'] or ''}"
                for corner, distance in zip(corners, distances)
                if distance is None
            ]
        # In the order they come round the lap, each corner owns the track
        # from half-way back to the one before to half-way on to the next.
        found.sort()
        along = [row["distance_m"] for row in rows]
        brakings = _brakings(rows, along)
        for place, (distance, index) in enumerate(found):
            start = (found[place - 1][0] + distance) / 2 if place else -math.inf
            end = (distance + found[place + 1][0]) / 2 if place + 1 < len(found) else math.inf
            placed_at[index].append(distance)
            event = _corner_event(rows, along, brakings, distance, start, end)
            if event is not None:
                by_corner[index][driver] = _corner_driver_row(driver, event, distance)
    if not any(placed_at):
        return None
    rows_by_corner = [
        {
            "corner_number": corner["number"],
            "letter": corner["letter"],
            "distance_m": _round_or_none(
                corner["distance_m"]
                if corner["distance_m"] is not None
                else (median(placed_at[index]) if placed_at[index] else None),
                1,
            ),
            "x": _round_or_none(corner["x"], 2),
            "y": _round_or_none(corner["y"], 2),
            "drivers": [by_corner[index][driver] for driver in sorted(by_corner[index])],
        }
        for index, corner in enumerate(corners)
    ]
    return rows_by_corner, not_passed


def _corners_on_lap(
    rows: list[dict[str, Any]], corners: list[dict[str, Any]], scale: float
) -> list[float | None]:
    """How far round this lap each corner is, by the lap's own distance. None for one the lap does not show.

    ``scale`` turns a corner's official distance into this lap's. The lap
    went all the way round.

    A corner is where the lap's line passes it. Where the line passes it more
    than once, or passes another corner's place on the way to somewhere else,
    the pass that is the corner is the one where the corner should be along
    the lap. That used to be taken from the corner's official distance alone,
    give or take 200 m, and a lap can be further out than that all the way
    round: a first lap is counted from the grid, and a stretch with no car
    data leaves the lap's distance long from there on. On Colapinto's lap 53
    of the 2026 Italian GP the first Lesmo is 2,757 m round, 233 m on from
    its official distance. The pass was thrown out, and the corner put at a
    sample 37 m before it that happened to be within reach. So how far the
    lap's own distance is out is measured first, from the corners it passes
    once, and each corner is then looked for where that puts it.
    """
    expected = [corner["distance_m"] * scale if corner["distance_m"] is not None else None for corner in corners]
    passes = [_passes(rows, corner) for corner in corners]
    out = [found[0][1] - where for found, where in zip(passes, expected) if len(found) == 1 and where is not None]
    shift = float(median(out)) if out else 0.0
    placed: list[float | None] = []
    for found, where in zip(passes, expected):
        due = where + shift if where is not None else None
        near = [item for item in found if due is None or abs(item[1] - due) <= OFFICIAL_CORNER_SEARCH_M]
        if near:
            placed.append(min(near)[1])
        elif found:
            # The lap passed the corner, and it is the lap's distance that is out.
            placed.append(min(found)[1])
        elif due is not None and rows[0]["distance_m"] <= due <= rows[-1]["distance_m"] and not any(
            _number(row.get("x")) and _number(row.get("y")) and abs(row["distance_m"] - due) <= OFFICIAL_CORNER_REACH_M
            for row in rows
        ):
            # No position data where the corner should be. The lap went all
            # the way round, so it can still be read by distance, as far as
            # its samples run. Where it has position data there and the line is
            # nowhere near the corner, the car did not go through it:
            # Antonelli's lap 9 of the 2025 British GP ends down the pit
            # entry, 99 m from turn 17, which was given his figures there.
            placed.append(due)
        else:
            placed.append(None)
    return placed


def _passes(rows: list[dict[str, Any]], corner: dict[str, Any]) -> list[tuple[float, float]]:
    """Each time a lap's line comes within reach of a corner: how near it comes, squared, and how far round the lap.

    A pass runs from where the line comes within reach to where it next goes
    out of it, or stops, and is where the line is nearest: between two
    samples, where that is nearer than either. It used to be at the nearest
    sample. Either feed can miss a second, and the samples either side of a
    corner are then far from it: on Piastri's lap 61 of the 2026 Dutch GP the
    nearest sample to turn 14 is 37 m from the corner and 39 m further round
    the lap than where the line between two samples passes 9 m from it,
    which is where the lap comparison's chart draws the corner.
    """
    if corner["x"] is None or corner["y"] is None:
        return []
    reach = (OFFICIAL_CORNER_REACH_M * POSITION_UNITS_PER_METRE) ** 2
    line = [
        (float(row["x"]), float(row["y"]), float(row["distance_m"]))
        for row in rows
        if _number(row.get("x")) and _number(row.get("y"))
    ]
    step = (OFFICIAL_CORNER_LINE_STEP_M * POSITION_UNITS_PER_METRE) ** 2
    passes: list[tuple[float, float]] = []
    nearest: tuple[float, float] | None = None
    for index, (x, y, along) in enumerate(line):
        here = ((x - corner["x"]) ** 2 + (y - corner["y"]) ** 2, along)
        joined = False
        if index + 1 < len(line):
            step_x, step_y = line[index + 1][0] - x, line[index + 1][1] - y
            length = step_x**2 + step_y**2
            joined = length <= step
            if joined and length > 0:
                # The place on the line between this sample and the next that is nearest the corner.
                share = min(1.0, max(0.0, ((corner["x"] - x) * step_x + (corner["y"] - y) * step_y) / length))
                off = (x + share * step_x - corner["x"]) ** 2 + (y + share * step_y - corner["y"]) ** 2
                if off < here[0]:
                    here = (off, along + share * (line[index + 1][2] - along))
        if here[0] <= reach and (nearest is None or here[0] < nearest[0]):
            nearest = here
        if nearest is not None and (here[0] > reach or not joined):
            passes.append(nearest)
            nearest = None
    return passes


def _brakings(rows: list[dict[str, Any]], along: list[float]) -> list[list[tuple[int, int]]]:
    """A lap's brakings, in order: each the brake applications that make it up, from first sample to last.

    The brake coming off and going on again is one braking, taken up again,
    when it goes on within 80 m and the car has not gained 8 km/h, the least
    a braking has to take off to be counted. A car that has gained it has
    been driven on from one corner and is being slowed for another: on
    Albon's lap 78 of the 2026 Monaco GP the brake comes off at 79 km/h for
    turn 5 and goes on again 74 m later, at 140 km/h, for the hairpin. Those
    were one braking, and the hairpin's.
    """
    brakings: list[list[tuple[int, int]]] = []
    for run in _brake_runs(rows):
        came_off = brakings[-1][-1][1] if brakings else None
        if came_off is not None and _taken_up_again(rows, came_off, run[0]):
            brakings[-1].append(run)
        else:
            brakings.append([run])
    return brakings


def _taken_up_again(rows: list[dict[str, Any]], came_off: int, back_on: int) -> bool:
    """Whether the brake going on at one sample is the braking it came off from at another, taken up again.

    What the car gains is looked for at every sample between the two, from
    the slowest it has been since the brake came off. Looked for at the two
    ends alone, it was missed where the car went on slowing first: on
    Bearman's lap 49 of the 2025 Japanese GP the brake comes off at 91 km/h
    in the chicane, the car slows to 85, gathers speed to 103, and the brake
    goes on again at 97. That was 6 km/h gained and one braking, and the
    second part of the chicane was published as braked for from 255 km/h.
    """
    if rows[back_on]["distance_m"] - rows[came_off]["distance_m"] > SAME_BRAKING_GAP_M:
        return False
    slowest = math.inf
    for row in rows[came_off : back_on + 1]:
        if not _number(row.get("speed_kph")):
            continue
        speed = float(row["speed_kph"])
        slowest = min(slowest, speed)
        if speed - slowest >= MIN_BRAKING_SPEED_LOSS_KPH:
            return False
    return True


def _corner_event(
    rows: list[dict[str, Any]],
    along: list[float],
    brakings: list[list[tuple[int, int]]],
    distance: float,
    start: float,
    end: float,
) -> dict[str, Any] | None:
    """A driver's figures for one official corner, which is at ``distance`` and whose stretch is ``start`` to ``end``.

    A braking is the corner's when the car is still slowing from it in the
    corner's stretch, and has lost 8 km/h by its slowest point there. It is
    slowing from it until it has gathered 8 km/h from the slowest it has
    been, which is a car driven on; until the next braking begins; and no
    further than 250 m past where the brake came off.

    The rule used to be that the braking's slowest point is in the stretch,
    which gave a braking to one corner only: a braking through two corners
    left the first published as not braked for, as the first part of a
    chicane was. Then that, or the brake on in the stretch before the
    corner. Both turned on which side of a line a sample fell. Placing the
    corners between samples moved them a metre or two, and 35 rows went
    from braked for to not: a brake that goes on 3 m past turn 5 in Bahrain
    and takes 33 km/h off in turn 5's stretch, and the second part of a
    chicane whose slowest sample is a metre short of its stretch. What a
    row says now changes with how much the car slows in the stretch, and
    not with where a line is drawn through one sample.
    """
    first, last = bisect_left(along, start), bisect_left(along, end)
    counted = []
    for position, braking in enumerate(brakings):
        began, came_off = braking[0][0], braking[-1][1]
        if began >= last:
            break
        # The slowest point of a braking is before the next braking begins.
        # Looked for 250 m on regardless, Albon's braking for turn 12 on lap
        # 36 of the 2026 Australian GP, from 204 km/h to 188, found the 108
        # km/h of turn 13: turn 12 was published as not braked for, and turn
        # 13 with a brake point 287 m before it.
        until = brakings[position + 1][0][0] if position + 1 < len(brakings) else len(rows)
        reach = along[came_off] + BRAKING_REACH_M
        on_samples = [
            index for on, off in braking for index in range(on, off + 1) if _number(rows[index].get("speed_kph"))
        ]
        # With the brake on, on the way to the corner. A brake that only goes
        # on past the corner is taken as far as the end of the corner's stretch.
        approach = [index for index in on_samples if along[index] <= distance]
        braked = approach or [index for index in on_samples if index < last]
        if not braked or not _number(rows[began].get("speed_kph")):
            continue
        # The car slows for the corner from the fastest it is on the way
        # there with the brake on. That is where the braking begins, unless
        # the brake reads on while the car gathers speed: on Stroll's lap 36
        # of the 2026 Australian GP it reads on for 636 m, most of it at full
        # throttle, from 150 km/h up to 253 and down to 189 for turn 6.
        # Counted from where the reading went on the car lost nothing, and
        # turn 6 was published as not braked for.
        peak = max(braked, key=lambda index: float(rows[index]["speed_kph"]))
        # The samples the car is still slowing from the braking at.
        slowing: list[int] = []
        lowest = math.inf
        for index in range(peak, until):
            if along[index] > reach:
                break
            if not _number(rows[index].get("speed_kph")):
                continue
            speed = float(rows[index]["speed_kph"])
            if speed - lowest >= MIN_BRAKING_SPEED_LOSS_KPH:
                # Driven on: what the car does from here is not this braking's.
                break
            lowest = min(lowest, speed)
            slowing.append(index)
        here = [index for index in slowing if first <= index < last]
        if not here:
            continue
        # The corner's slowest point is the slowest of the braking in the corner's stretch.
        apex = min(here, key=lambda index: float(rows[index]["speed_kph"]))
        entry_speed, apex_speed = float(rows[began]["speed_kph"]), float(rows[apex]["speed_kph"])
        fastest = float(rows[peak]["speed_kph"])
        braking_distance = float(along[apex] - along[began])
        if fastest - apex_speed < MIN_BRAKING_SPEED_LOSS_KPH or braking_distance < MIN_BRAKING_DISTANCE_M:
            continue
        # A braking that begins straight after a sample with no brake reading
        # began somewhere in the stretch with none: its first sample is where
        # the reading came back, not where the driver began to brake. Nor is
        # it where a reading went on with the car still to gather speed.
        gathered = fastest - min(float(rows[index]["speed_kph"]) for index in braked if index <= peak)
        began_unread = (began > 0 and rows[began - 1].get("brake", False) is None) or (
            gathered >= MIN_BRAKING_SPEED_LOSS_KPH
        )
        # For this corner the brake is last on where the last application
        # begun before the slowest point came off.
        last_on = max(off for on, off in braking if on <= apex)
        ended_unread = last_on + 1 < len(rows) and rows[last_on + 1].get("brake", False) is None
        start_time = _interpolate(rows, along[began], "_elapsed_ms")
        end_time = _interpolate(rows, along[last_on], "_elapsed_ms")
        counted.append(
            {
                "brake_start_m": None if began_unread else along[began],
                "apex_distance_m": float(along[apex]),
                "braking_distance_m": None if began_unread else braking_distance,
                "entry_speed_kph": None if began_unread else entry_speed,
                "apex_speed_kph": apex_speed,
                "exit_speed_kph": _interpolate(rows, min(along[-1], along[apex] + 150), "speed_kph"),
                "speed_loss_kph": None if began_unread else entry_speed - apex_speed,
                "brake_duration_ms": end_time - start_time
                if end_time is not None and start_time is not None and not began_unread and not ended_unread
                else None,
                "braking": "began_unread" if began_unread else "seen",
            }
        )
    if counted:
        return min(counted, key=lambda item: abs(item["apex_distance_m"] - distance))

    # No braking is the corner's. Its slowest point is looked for before the
    # brake next goes on past it, which is for another corner.
    runs = [run for braking in brakings for run in braking]
    following = next((along[on] for on, _ in runs if along[on] > distance), math.inf)
    event = _slowest_point_near(
        rows,
        distance,
        max(start, distance - OFFICIAL_CORNER_WINDOW_M),
        min(end, distance + OFFICIAL_CORNER_WINDOW_M),
        following,
    )
    if event is None:
        return None
    # That is a driver who did not brake only if the brake was read all the
    # way in: Gasly's lap 56 of the 2026 Australian GP has no reading for the
    # 365 m before turn 9, from 311 km/h to 218, and was published as "no
    # braking". All the way in is from where the corner's own stretch of
    # track begins. And a brake that is on where its reading comes back, on
    # the way in, is a driver who braked, however little of it was seen.
    came_back_on = any(
        on > 0 and rows[on - 1].get("brake", False) is None and start <= along[on] <= event["apex_distance_m"]
        for on, _ in runs
    )
    if came_back_on:
        event["braking"] = "began_unread"
    elif _brake_unread(rows, start, event["apex_distance_m"]):
        event["braking"] = "unread"
    else:
        event["braking"] = "none"
    return event


def _brake_unread(rows: list[dict[str, Any]], start: float, end: float) -> bool:
    """Whether any sample of a stretch of a lap has no brake reading."""
    return any(start <= row["distance_m"] <= end and row.get("brake", False) is None for row in rows)


def _slowest_point_near(
    rows: list[dict[str, Any]], distance: float, start: float, end: float, before: float = math.inf
) -> dict[str, Any] | None:
    """The slowest sample around a corner the driver did not brake for, as a corner event.

    Looked for from ``start`` to ``end``, and short of ``before``.
    """
    window = [
        row
        for row in rows
        if start <= row["distance_m"] <= end and row["distance_m"] < before and _number(row.get("speed_kph"))
    ]
    if not window:
        return None
    apex = min(window, key=lambda row: (float(row["speed_kph"]), abs(row["distance_m"] - distance)))
    return {
        "apex_distance_m": float(apex["distance_m"]),
        "apex_speed_kph": float(apex["speed_kph"]),
        "exit_speed_kph": _interpolate(
            rows, min(rows[-1]["distance_m"], apex["distance_m"] + 150), "speed_kph"
        ),
    }


def calculate_car_performance(
    session_id: str,
    laps: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
) -> dict[str, Any]:
    # Each driver's lap is the one track dominance compares. It used to be the
    # fastest lap with any telemetry, and for a driver out early that is what
    # they managed: in the 2026 Monaco GP Verstappen's only lap, lap 1, which
    # has no lap time and stops 2,107 m round, was profiled and averaged into
    # Red Bull's figures, and in the 2026 Austrian GP so was Bottas's lap 1.
    representatives, samples, left_out = fastest_complete_telemetry_laps(laps, telemetry)
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
    caveats = [
        "Profiles use each driver's fastest clean lap with complete telemetry: accurate, not deleted, "
        "not a pit lap, not lap 1 and not run under a safety car, VSC or red flag.",
        "A team's figures are the mean of its drivers' profiles.",
        "Speed bands are sample averages: low <150, medium 150-250, high >=250 km/h.",
        "Maximum speed is telemetry-derived and may differ from the official speed trap.",
        "Throttle and braking percentages exclude samples where that channel is unavailable.",
        "A sample at which the car has not moved since the one before, as when it stands in its pit box, is left out of every figure.",
    ]
    if left_out:
        caveats.insert(
            1, f"Left out, having no such lap, and so not in their team's figures: {', '.join(left_out)}."
        )
    return {
        "session_id": session_id,
        "drivers": driver_rows,
        "teams": teams,
        "caveats": caveats,
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
    """A rate of tyre wear for each stint, fitted to its clean laps' times against tyre age.

    A stint is a run of laps on one set, as ``stints.json`` has them
    (``f1data.normalize.stints``, whose rule ``_tyre_runs`` repeats): a lap
    F1 names no compound for is on the set its stint number says, and the
    stint has the compound F1 names for any of its laps. The laps used to be
    grouped by their own compound, so a stint whose compound F1 names a few
    laps after it went on was fitted as two rows with one stint number, each
    with part of the laps. And the laps F1's tyre data gives no stint for
    went into a row of "stint 0" with no compound: in the 2025 Miami GP,
    whose tyre data begins on lap 25, one for each of 15 drivers, said to be
    short of tyre ages because F1 gives none for a set that went on used. F1
    does give them, and these laps have no tyre data at all. They are in no
    row, and the result says how many there are.
    """
    fuel_correction = _fuel_correction(summary, session_id)

    rows = []
    no_stint: list[dict[str, Any]] = []
    # The rows come in the order of each stint's first clean lap, as they did.
    where = {id(lap): index for index, lap in enumerate(laps)}
    runs = [(run, group) for run in _tyre_runs(laps) if (group := clean_laps(run["laps"]))]
    for run, group in sorted(runs, key=lambda item: where[id(item[1][0])]):
        if run["stint"] is None:
            no_stint.extend(group)
            continue
        driver, stint, compound = run["driver"], run["stint"], run["compound"]
        samples = [
            (float(lap["tyre_age"]), float(lap["lap_time_ms"]))
            for lap in group
            if lap.get("tyre_age") is not None and lap.get("lap_time_ms") is not None
        ]
        # Every row carries every field; a fit that is not reported keeps its
        # rate fields empty and says why in ``fit_status`` and ``caveats``.
        row: dict[str, Any] = {
            "driver_code": driver,
            "compound": compound,
            "stint": stint,
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
            # A stint can be short of laps to fit and not of clean laps: F1's
            # tyre data can give a stint and no tyre age. Bearman's third
            # stint of the 2026 Barcelona GP has 19 clean laps and an age for
            # none, and was said to have "0 clean laps".
            if len(samples) == len(group):
                why = f"{len(group)} clean laps, and at least {MIN_DEGRADATION_LAPS} are required."
            else:
                why = (
                    f"F1's tyre data gives a tyre age for {len(samples)} of the stint's "
                    f"{len(group)} clean laps, and at least {MIN_DEGRADATION_LAPS} with one are "
                    "required."
                )
            rows.append({**row, "fit_status": "too_few_laps", "caveats": [f"No rate reported: {why}"]})
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
    caveats = [
        "Fuel correction is an explicit generic assumption, not measured car fuel mass.",
        "Pit, deleted, inaccurate, neutralized, and statistical outlier laps are excluded.",
        "Track evolution, traffic, weather, and tyre management remain confounding factors.",
        f"A rate is reported only for a stint with at least {MIN_DEGRADATION_LAPS} clean "
        "laps whose fitted slope has a standard error of at most "
        f"{MAX_SLOPE_STANDARD_ERROR_MS_PER_LAP:.0f} ms/lap or "
        f"{MAX_SLOPE_RELATIVE_STANDARD_ERROR:.0%} of the slope. R² is shown but does not "
        "decide this: a tyre that barely degrades has an R² near zero however clean the "
        "stint.",
    ]
    if no_stint:
        drivers = sorted({str(lap.get("driver_code")) for lap in no_stint})
        bare = all(
            _named_compound(lap.get("compound")) is None and lap.get("tyre_age") is None for lap in no_stint
        )
        caveats.append(
            f"F1's tyre data gives no stint for {len(no_stint)} clean laps, of {', '.join(drivers)}, "
            "so the set they were run on is not known and they are in no row."
            + (" It gives no compound or tyre age for them either." if bare else "")
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
        "caveats": caveats,
    }


def _tyre_runs(laps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each driver's runs of laps on one set of tyres, by the rule of ``f1data.normalize.stints``.

    The analyses are given laps and not stints, and cannot import that
    module, so the rule is here too. Driver by driver in lap order, a new
    stint number starts a new run, and so does a compound that changes to
    another under one number, which is F1 correcting itself. A lap with no
    compound does not: under the same number it is the same set, and the run
    has the compound F1 does name. Laps with no stint number make runs whose
    stint is None.
    """
    by_driver: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lap in laps:
        driver = str(lap.get("driver_code") or "").upper()
        if driver and lap_number(lap) is not None:
            by_driver[driver].append(lap)
    runs: list[dict[str, Any]] = []
    for driver, driver_laps in by_driver.items():
        current: dict[str, Any] | None = None
        for lap in sorted(driver_laps, key=lambda row: lap_number(row) or 0):
            compound = _named_compound(lap.get("compound"))
            stint = _stint_number(lap.get("stint"))
            same_set = (
                current is not None
                and current["stint"] == stint
                and (compound is None or current["compound"] is None or current["compound"] == compound)
            )
            if current is None or not same_set:
                current = {"driver": driver, "stint": stint, "compound": compound, "laps": []}
                runs.append(current)
            current["compound"] = current["compound"] or compound
            current["laps"].append(lap)
    return runs


# How FastF1 and the old pipeline write a compound F1 did not name.
_UNNAMED_COMPOUNDS = {"", "NAN", "NONE", "UNKNOWN", "TEST_UNKNOWN"}


def _named_compound(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.upper() in _UNNAMED_COMPOUNDS else text


def _stint_number(value: Any) -> int | None:
    """A stint number, or None for one that is missing or is no stint. F1 counts stints from 1."""
    number = _float(value)
    return int(number) if number is not None and number >= 1 else None


def _fuel_correction(summary: dict[str, Any], session_id: str) -> float:
    """Fuel-burn correction for the session, matched on its exact type.

    This used to test whether the name contained "sprint", which is also true
    of "Sprint Qualifying" and "Sprint Shootout": qualifying sessions, run on
    a few laps of fuel, were given the 35 ms/lap sprint-race correction.

    The session's code is read before its name. A name means different
    things in different years: the sprint of 2021 was called Sprint
    Qualifying, which since 2024 is the session that sets a sprint's grid,
    and read by its name it was given no correction. The old pipeline's
    summary has a name and no code.
    """
    session_type = str(summary.get("type") or summary.get("session") or "").strip().lower()
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


class TelemetryByLap:
    """Telemetry samples by driver and lap, grouped from a flat list of rows.

    The analyses here take telemetry as one list of sample rows and group it
    themselves. A race at full resolution is about 750,000 samples, of which
    they read fewer than fifty laps, so a caller that holds telemetry in
    another form can pass an object with these four methods instead of the
    list (``telemetry_by_lap``). Only the laps an analysis reads then have to
    be turned into rows.
    """

    def __init__(self, telemetry: list[dict[str, Any]], lap_number_of: Any) -> None:
        self._rows: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in telemetry:
            driver = str(row.get("driver_code") or "").upper()
            number = lap_number_of(row)
            if driver and number > 0 and _number(row.get("distance_m")):
                self._rows[(driver, number)].append(row)

    def lap_keys(self) -> list[tuple[str, int]]:
        """Every (driver code, lap number) with at least one sample that has a distance."""
        return list(self._rows)

    def lap_sample_count(self, key: tuple[str, int]) -> int:
        return len(self._rows.get(key, ()))

    def lap_end_m(self, key: tuple[str, int]) -> float:
        """The furthest distance the lap's samples reach."""
        return max(float(row["distance_m"]) for row in self._rows[key])

    def lap_rows(self, key: tuple[str, int]) -> list[dict[str, Any]]:
        return self._rows.get(key, [])


def telemetry_by_lap(telemetry: Any, lap_number_of: Any) -> Any:
    """``telemetry`` grouped by lap, whether it came as rows or already by lap."""
    if hasattr(telemetry, "lap_rows"):
        return telemetry
    return TelemetryByLap(telemetry, lap_number_of)


def fastest_complete_telemetry_laps(
    laps: list[dict[str, Any]], telemetry: Any, by_distance: bool = True
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[str]]:
    """Pick each driver's fastest clean lap whose telemetry runs line to line.

    The telemetry analyses used to take the fastest non-deleted lap that has
    any telemetry, which for a driver who retires early is whatever they
    managed. In the 2026 Austrian GP Bottas completed lap 1 and an in-lap, so
    his lap 1 (84.016 s) was compared with flying laps of 70 to 74 s and won
    6 of 25 minisectors. Its telemetry measures 4,495 m against 4,287 m for a
    normal lap, so his distance axis was up to 208 m, more than a minisector,
    out of step: his straights were timed against everyone else's corners.

    Here a lap must pass ``clean_laps`` (accurate, not deleted, not a pit lap,
    not lap 1, not neutralised) and its telemetry must be complete: it runs
    the length of the lap's time and, with ``by_distance``, starts at the
    line and measures what a normal lap does (``_covers_lap``). The corner
    table asks the clock alone. It finds a corner by position, and a lap that
    ran its time went all the way round whatever its distance says
    (``OFFICIAL_CORNER_REACH_M``). A driver with no such lap is left out and
    named in the third return value. Yellow flags are allowed: the status is
    session-wide, and a lap that is still the driver's fastest was evidently
    not slowed by one.
    """
    by_lap = telemetry_by_lap(telemetry, lambda row: lap_number(row) or 0)

    drivers = {key[0] for key in by_lap.lap_keys()}
    drivers.update(str(lap["driver_code"]).upper() for lap in laps if lap.get("driver_code"))

    # (lap time, lap number, lap) per driver: sorts fastest first, earliest on a tie.
    candidates: dict[str, list[tuple[float, int, dict[str, Any]]]] = defaultdict(list)
    for lap in clean_laps(laps):
        driver = str(lap.get("driver_code") or "").upper()
        number = lap_number(lap) or 0
        lap_time = _float(lap.get("lap_time_ms"))
        if lap_time is None or not by_lap.lap_sample_count((driver, number)):
            continue
        candidates[driver].append((lap_time, number, lap))
    usual_end = _usual_lap_end(laps, by_lap)

    representatives = []
    selected: dict[str, list[dict[str, Any]]] = {}
    for driver, driver_laps in sorted(candidates.items()):
        for lap_time, number, lap in sorted(driver_laps, key=lambda item: item[:2]):
            rows = _prepare_samples(by_lap.lap_rows((driver, number)))
            whole = (
                _covers_lap(rows, lap_time, usual_end)
                if by_distance
                else len(rows) >= 3 and _runs_its_lap_time(rows, lap_time)
            )
            if not whole:
                continue
            selected[driver] = rows
            representatives.append(
                {"driver_code": driver, "lap_number": number, "lap_time_ms": lap["lap_time_ms"]}
            )
            break
    return representatives, selected, sorted(drivers - set(selected))


def _usual_lap_end(laps: list[dict[str, Any]], by_lap: Any) -> float:
    """How far the telemetry of a normal lap runs, or 0 when no lap says.

    The length of a normal lap is not an input, so it is taken from the laps
    themselves: most clean laps are complete, and the median ignores the rest.
    """
    ends = []
    for lap in clean_laps(laps):
        key = (str(lap.get("driver_code") or "").upper(), lap_number(lap) or 0)
        if _float(lap.get("lap_time_ms")) is not None and by_lap.lap_sample_count(key):
            ends.append(by_lap.lap_end_m(key))
    return float(median(ends)) if ends else 0.0


def _runs_its_lap_time(rows: list[dict[str, Any]], lap_time_ms: float | None) -> bool:
    """True when the lap was timed and its prepared telemetry runs the length of that time.

    Such a lap went from line to line, whatever its telemetry says of the
    distance. One with no lap time, or whose telemetry stops before the time
    is up, did not, or cannot be shown to have.
    """
    if lap_time_ms is None or lap_time_ms <= 0:
        return False
    if any(_float(row.get("relative_time_ms")) is None for row in (rows[0], rows[-1])):
        # No clock was recorded and ``_prepare_samples`` rebuilt one from
        # speed and distance, so there is nothing independent to compare.
        return True
    elapsed = rows[-1]["_elapsed_ms"] - rows[0]["_elapsed_ms"]
    return abs(elapsed - lap_time_ms) <= TELEMETRY_LAP_TIME_TOLERANCE * lap_time_ms


def _covers_lap(rows: list[dict[str, Any]], lap_time_ms: float, usual_end: float) -> bool:
    """True when prepared telemetry runs the whole lap, in distance and on the clock."""
    if len(rows) < 3 or usual_end <= 0 or lap_time_ms <= 0:
        return False
    slack = TELEMETRY_LAP_DISTANCE_TOLERANCE * usual_end
    if rows[0]["distance_m"] > slack or abs(rows[-1]["distance_m"] - usual_end) > slack:
        return False
    return _runs_its_lap_time(rows, lap_time_ms)


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


def _brake_runs(rows: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """A lap's brake applications: the first and the last sample of each stretch with the brake on."""
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
    return runs


def _braking_events(driver: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The brakings of a lap, wherever they are: what corners are inferred from without the circuit's.

    A braking is what the official corners take one to be (``_brakings``).
    Here the brake going on again within 80 m used to be the same braking
    however much speed the car had gathered in between, so two corners close
    together were inferred as one: a braking from 300 km/h to 100, 70 m at
    full throttle up to 160, and a braking to 70 were one corner, braked for
    from 300 km/h to 70.
    """
    along = [row["distance_m"] for row in rows]
    merged = [(braking[0][0], braking[-1][1]) for braking in _brakings(rows, along)]

    events = []
    for position, (start_index, end_index) in enumerate(merged):
        # A run that begins straight after a sample with no brake reading
        # began somewhere in the stretch with none: its first sample is where
        # the reading came back, not where the driver began to brake.
        began_unread = start_index > 0 and rows[start_index - 1].get("brake", False) is None
        ended_unread = end_index + 1 < len(rows) and rows[end_index + 1].get("brake", False) is None
        start_distance = rows[start_index]["distance_m"]
        search_end = rows[end_index]["distance_m"] + BRAKING_REACH_M
        # The slowest point of a braking is before the next braking begins.
        last_index = merged[position + 1][0] if position + 1 < len(merged) else len(rows)
        window = [
            row
            for row in rows[start_index:last_index]
            if row["distance_m"] <= search_end and _number(row.get("speed_kph"))
        ]
        if not window or not _number(rows[start_index].get("speed_kph")):
            continue
        apex = min(window, key=lambda row: float(row["speed_kph"]))
        entry_speed = float(rows[start_index]["speed_kph"])
        apex_speed = float(apex["speed_kph"])
        braking_distance = float(apex["distance_m"] - start_distance)
        if entry_speed - apex_speed < MIN_BRAKING_SPEED_LOSS_KPH or braking_distance < MIN_BRAKING_DISTANCE_M:
            continue
        exit_speed = _interpolate(rows, min(rows[-1]["distance_m"], apex["distance_m"] + 150), "speed_kph")
        start_time = _interpolate(rows, start_distance, "_elapsed_ms")
        end_time = _interpolate(rows, rows[end_index]["distance_m"], "_elapsed_ms")
        events.append(
            {
                "driver_code": driver,
                "brake_start_m": None if began_unread else start_distance,
                "apex_distance_m": float(apex["distance_m"]),
                "braking_distance_m": None if began_unread else braking_distance,
                "entry_speed_kph": None if began_unread else entry_speed,
                "apex_speed_kph": apex_speed,
                "exit_speed_kph": exit_speed,
                "speed_loss_kph": None if began_unread else entry_speed - apex_speed,
                "brake_duration_ms": end_time - start_time
                if end_time is not None and start_time is not None and not began_unread and not ended_unread
                else None,
                "braking": "began_unread" if began_unread else "seen",
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
