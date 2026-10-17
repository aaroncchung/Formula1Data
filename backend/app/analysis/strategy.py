"""Stint, pit-stop and undercut/overcut summary. Returns plain dictionaries."""

from collections import Counter, defaultdict
from statistics import median
from typing import Any

from .common import clean_laps, has_yellow, is_neutralized, lap_number, robust_spread


# Laps on each side of a stop that form the driver's baseline. Five is enough
# for the median to shrug off a lap or two lost to traffic, and few enough that
# fuel burn (about 55 ms a lap) and tyre wear move the baseline by a few tenths
# against a loss of about twenty seconds. On the 2026 Austrian GP the estimate
# is 21.5 s with three laps a side, 21.3 s with five and 21.4 s with eight.
PIT_LOSS_BASELINE_WINDOW_LAPS = 5
# A baseline from one or two laps is those laps, not a pace.
PIT_LOSS_MIN_BASELINE_LAPS = 3
# With three stops the median already ignores one slow stop; with fewer it is
# just a stop, or the mean of two.
PIT_LOSS_MIN_STOPS = 3

# How far from the stop the laps compared across it may be. The comparison is
# meant to be the last lap on the old tyres against the first on the new ones,
# so every lap of slack adds fuel burn and tyre wear to it. Three laps allows
# for a deleted lap or a yellow flag next to the stop and no more.
PACE_CHANGE_WINDOW_LAPS = 3

_PIT_LOSS_EXCLUSIONS = {
    "no_lap_number": "no lap number",
    "red_flag_wait": "the car waiting in the pit lane through a red flag",
    "no_stop": "the car going through without stopping",
    "missing_lap_time": "no in-lap or out-lap time",
    "first_lap": "pitted on the standing-start lap",
    "back_to_back_stops": "stops on consecutive laps",
    "not_green": "a yellow flag, safety car, VSC or red flag on the in-lap or out-lap",
    "too_few_baseline_laps": (
        f"fewer than {PIT_LOSS_MIN_BASELINE_LAPS} clean green-flag laps around the stop"
    ),
}


def calculate_strategy(
    session_id: str,
    stints: list[dict[str, Any]],
    pit_stops: list[dict[str, Any]],
    laps: list[dict[str, Any]],
    race_control: list[dict[str, Any]],
) -> dict[str, Any]:
    compound_usage = Counter(stint.get("compound") for stint in stints)
    laps_by_key = {
        (_driver(lap), number): lap
        for lap in laps
        if (number := lap_number(lap)) is not None
    }
    green = _green_lap_times(laps)

    pit_loss = _pit_loss(pit_stops, laps_by_key, green)
    pit_lane_time = _pit_lane_time(pit_stops)
    reported = _says_which_f1_reports(pit_stops)

    by_driver: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stop in pit_stops:
        by_driver[stop["driver_code"]].append(stop)

    undercut_overcut = []
    for driver, stops in by_driver.items():
        # dict.get(key, default) only substitutes the default when the key is
        # absent, so a present-but-null lap number used to reach min() and
        # int() unguarded. Drop stops with no usable lap number instead.
        #
        # And an entry to the pit lane that was no pit stop is not a stop to
        # compare tyres across. In the 2025 Australian GP the field followed
        # the safety car down the pit lane on laps 2 to 4, and each driver's
        # first stop was taken to be lap 2. In the 2026 Dutch GP it was the
        # wait through the red flag on lap 2, tyres changed or not.
        stop_laps = sorted(
            number
            for number in (lap_number(stop) for stop in stops if _not_a_stop(stop) is None)
            if number is not None
        )
        if not stop_laps:
            continue
        next_stop_lap = stop_laps[1] if len(stop_laps) > 1 else None
        undercut_overcut.append(
            _pace_change_across_stop(
                driver, stop_laps[0], next_stop_lap, green.get(str(driver).upper(), {})
            )
        )

    return {
        "session_id": session_id,
        "stints": stints,
        "compound_usage": dict(compound_usage),
        "pit_stops": pit_stops,
        "pit_loss_estimate_ms": pit_loss["estimate_ms"],
        "pit_loss": pit_loss,
        "pit_lane_time": pit_lane_time,
        "undercut_overcut": undercut_overcut,
        "race_control_overlays": race_control,
        "caveats": [
            _pit_loss_caveat(pit_loss),
            "Pit-lane time is the transit from pit entry to pit exit, where FastF1 provides "
            "adjacent pit-in/out timestamps, "
            + (
                "over the stops F1's pit-stop feed reports: a car can go down the pit lane "
                "without stopping, and the timing alone does not say which did."
                if reported
                else "over every entry to the pit lane that has one: the stop list does not say "
                "which entries F1's pit-stop feed reports."
            )
            + " It includes the stationary time and has no on-track baseline in it, so it is "
            "not pit loss.",
            "Pace change across a stop is, for the driver's first stop, their last clean "
            f"green-flag lap in the {PACE_CHANGE_WINDOW_LAPS} laps before the in-lap minus the "
            f"first one in the {PACE_CHANGE_WINDOW_LAPS} laps after the out-lap, and before "
            "their next stop; positive is quicker after the stop. Pit, deleted, inaccurate, "
            "yellow-flag and neutralised laps are never used, and no value is given when either "
            "lap is missing. A stop is nearly always a "
            "change of tyres, and not always: a penalty served or a repair made in the pit box "
            "is a stop on the same set"
            + (", and the stop list says which each was." if reported else "."),
            "A car that went down the pit lane without stopping, on a drive-through penalty or "
            "behind the safety car, made no stop: F1's pit-stop feed reports none, and its tyre "
            "data has the car on the same set afterwards. Nor did a car that waited in the pit "
            "lane through a red flag. Neither entry is in either figure."
            if reported
            else "The stop list does not say which entries to the pit lane were stops. A car that "
            "went down the pit lane without stopping, on a drive-through penalty or behind the "
            "safety car, or waited in it through a red flag, is taken for a stop.",
            "Pace change is descriptive: it is not adjusted for traffic, fuel or track "
            "evolution, and it is not a causal model of an undercut or overcut on a rival.",
        ],
    }


def _not_a_stop(stop: dict[str, Any]) -> str | None:
    """Why an entry to the pit lane was no pit stop, or ``None`` for one that is taken for a stop.

    The site reads the stop list the same way (``pitEntryKind`` in
    frontend/src/lib/strategy-view.ts), and in the same order, so that what
    the page counts as a stop is what the figures beside it are of.

    ``red_flag_wait``: the session was red-flagged while the car was in the
    pit lane. That is a wait for the restart whatever was done to the car
    meanwhile: tyres may be changed under a red flag, and three cars of the
    2025 Sao Paulo sprint waited 22 minutes on the ones they had.

    ``no_stop``: the car went down the pit lane without stopping, on a
    drive-through penalty or behind the safety car. Both of F1's feeds have
    to say so: its pit-stop feed gives the entry no stationary time, and its
    tyre data has the car on the same set afterwards (``tyres_changed`` in
    the stop list). Either alone is not enough. The pit-stop feed leaves out
    about one stop in eleven. And the tyre data can lag: in the 2025 Miami GP
    it has no change of tyres at twelve stops the pit-stop feed times, and
    shows each of them eight laps later.

    Where the feeds do not say, the entry is taken for a stop.
    """
    if stop.get("under_red_flag"):
        return "red_flag_wait"
    if stop.get("stationary_ms") is None and stop.get("tyres_changed") is False:
        return "no_stop"
    return None


def _pit_loss(
    pit_stops: list[dict[str, Any]],
    laps_by_key: dict[tuple[str, int], dict[str, Any]],
    green: dict[str, dict[int, float]],
) -> dict[str, Any]:
    """Estimate the time a stop costs against staying out.

    Pit-lane time cannot answer that: it has no on-track baseline in it, and
    one car parked in the lane drags a mean anywhere (a committed 2026 race
    reported 410,846 ms). Instead each stop is priced from lap times alone: the
    in-lap plus the out-lap cover two laps of track, so their sum minus twice
    the driver's clean pace around the stop is what the stop cost.
    """
    stops = [_stop_pit_loss(stop, laps_by_key, green) for stop in pit_stops]
    losses = [row["pit_loss_ms"] for row in stops if row["pit_loss_ms"] is not None]
    excluded = Counter(
        row["excluded_reason"] for row in stops if row["excluded_reason"] is not None
    )
    enough = len(losses) >= PIT_LOSS_MIN_STOPS
    return {
        "estimate_ms": round(median(losses), 1) if enough else None,
        "spread_ms": _rounded(robust_spread(losses)) if enough else None,
        "qualifying_stop_count": len(losses),
        "stop_count": len(stops),
        "minimum_stop_count": PIT_LOSS_MIN_STOPS,
        "baseline_window_laps": PIT_LOSS_BASELINE_WINDOW_LAPS,
        "excluded_stop_counts": dict(excluded),
        "stops": stops,
    }


def _stop_pit_loss(
    stop: dict[str, Any],
    laps_by_key: dict[tuple[str, int], dict[str, Any]],
    green: dict[str, dict[int, float]],
) -> dict[str, Any]:
    driver = _driver(stop)
    in_lap_number = lap_number(stop)
    row: dict[str, Any] = {
        "driver_code": stop.get("driver_code"),
        "lap_number": in_lap_number,
        "pit_loss_ms": None,
        "in_lap_ms": None,
        "out_lap_ms": None,
        "baseline_lap_ms": None,
        "baseline_lap_count": 0,
        "excluded_reason": None,
    }
    if in_lap_number is None:
        return {**row, "excluded_reason": "no_lap_number"}

    in_lap = laps_by_key.get((driver, in_lap_number), {})
    out_lap = laps_by_key.get((driver, in_lap_number + 1), {})
    in_time, out_time = in_lap.get("lap_time_ms"), out_lap.get("lap_time_ms")
    row.update({"in_lap_ms": in_time, "out_lap_ms": out_time})
    # What that cost is not what a pit stop costs. Colapinto's drive-through
    # penalty was in the median of the 2026 Dutch GP, priced at 13.0 s.
    not_a_stop = _not_a_stop(stop)
    if not_a_stop is not None:
        return {**row, "excluded_reason": not_a_stop}
    # A car that retires in the pits has no out-lap.
    if in_time is None or out_time is None:
        return {**row, "excluded_reason": "missing_lap_time"}
    if in_lap_number == 1:
        return {**row, "excluded_reason": "first_lap"}
    # A lap that both leaves and enters the pits belongs to two stops at once.
    if in_lap.get("is_pit_out_lap") or out_lap.get("is_pit_in_lap"):
        return {**row, "excluded_reason": "back_to_back_stops"}
    if not (_is_green(in_lap) and _is_green(out_lap)):
        return {**row, "excluded_reason": "not_green"}

    first, last = in_lap_number, in_lap_number + 1
    window = PIT_LOSS_BASELINE_WINDOW_LAPS
    baseline = [
        lap_time
        for number, lap_time in green.get(driver, {}).items()
        if first - window <= number < first or last < number <= last + window
    ]
    row["baseline_lap_count"] = len(baseline)
    if len(baseline) < PIT_LOSS_MIN_BASELINE_LAPS:
        return {**row, "excluded_reason": "too_few_baseline_laps"}
    baseline_lap = float(median(baseline))
    return {
        **row,
        "baseline_lap_ms": round(baseline_lap, 1),
        "pit_loss_ms": round(float(in_time) + float(out_time) - 2 * baseline_lap, 1),
    }


def _pit_loss_caveat(pit_loss: dict[str, Any]) -> str:
    method = (
        "in-lap plus out-lap minus twice the driver's median clean lap in the "
        f"{PIT_LOSS_BASELINE_WINDOW_LAPS} laps either side, for stops made under green"
    )
    used, total = pit_loss["qualifying_stop_count"], pit_loss["stop_count"]
    if pit_loss["estimate_ms"] is not None:
        text = f"Pit loss is the median across {used} of {total} entries to the pit lane of: {method}."
    elif not total:
        text = "No pit-loss estimate: no pit stops were recorded."
    else:
        text = (
            f"No pit-loss estimate: {used} of {total} entries to the pit lane qualified and at "
            f"least {PIT_LOSS_MIN_STOPS} are needed. A qualifying stop gives {method}."
        )
    left_out = [
        f"{count} for {_PIT_LOSS_EXCLUSIONS[reason]}"
        for reason, count in sorted(pit_loss["excluded_stop_counts"].items())
    ]
    return f"{text} Left out: {'; '.join(left_out)}." if left_out else text


def _pit_lane_time(pit_stops: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise the pit-lane transit times of the stops F1's pit-stop feed reports.

    The timing has every entry to the pit lane, and not every entry is a stop.
    In the 2025 Canadian GP the field followed the safety car down the pit
    lane three times, and 49 of that race's 82 entries are that: the median
    over all of them was 18.3 s, of cars that never stopped. The fastest of
    the 2026 Dutch GP was a drive-through penalty. Nothing in the timing
    tells such an entry from a stop reliably (a quick stop and a slow passage
    took the same 14.8 s in the 2025 Australian GP), so the figures are of
    the entries F1 itself gives a stationary time for.

    The median is used so a car held in the lane does not define the figure;
    the slowest time is still reported, labelled as the slowest. A car that
    sat in the lane through a red flag was not making a pit stop, and the
    twenty minutes it waited are left out.

    The old pipeline, which still runs on ``main``, writes stops with no
    stationary time at all: it does not read F1's pit-stop feed. Held to the
    rule above its pit-lane figures were always empty (the 2026 Austrian GP:
    41 of 44 entries timed, none counted). For such a list the figures are of
    every timed entry, as they were before the rule, and the caveat says so.
    """
    reported = _says_which_f1_reports(pit_stops)
    durations = [
        float(stop["duration_ms"])
        for stop in pit_stops
        if stop.get("duration_ms") is not None
        and (stop.get("stationary_ms") is not None or not reported)
        and not stop.get("under_red_flag")
    ]
    return {
        "median_ms": round(median(durations), 1) if durations else None,
        "fastest_ms": min(durations) if durations else None,
        "slowest_ms": max(durations) if durations else None,
        "timed_stop_count": len(durations),
        "stop_count": len(pit_stops),
    }


def _says_which_f1_reports(pit_stops: list[dict[str, Any]]) -> bool:
    """Whether the stop list says, entry by entry, which stops F1's pit-stop feed reports.

    Format 2 gives every entry a ``stationary_ms``, null where the feed has
    none. The old pipeline's entries have no such field. A list with no
    entries, as a sprint's often is, has nothing it does not say.
    """
    return not pit_stops or any("stationary_ms" in stop for stop in pit_stops)


def _pace_change_across_stop(
    driver: Any,
    stop_lap: int,
    next_stop_lap: int | None,
    green_laps: dict[int, float],
) -> dict[str, Any]:
    """Compare the last green lap on the old tyres with the first on the new.

    This used to take the nearest timed lap either side with no track-status
    filter, so a neutralisation next to the stop became a "gain": AR-08 records
    52,554 ms in one committed race, and in the 2026 Austrian GP Antonelli was
    given -16,945 ms because the lap after his out-lap ran under a VSC.

    A lap further away is no substitute. After a long neutralisation the next
    green lap is on different fuel and a different track, so beyond the window
    the answer is that there is nothing to report.
    """
    window = PACE_CHANGE_WINDOW_LAPS
    # stop_lap is the in-lap and stop_lap + 1 the out-lap. Their pit flags keep
    # both out of green_laps, so the window after the stop holds `window`
    # flying laps.
    last_after = stop_lap + 1 + window
    if next_stop_lap is not None:
        last_after = min(last_after, next_stop_lap - 1)
    before = max(
        (number for number in green_laps if stop_lap - window <= number < stop_lap),
        default=None,
    )
    after = min(
        (number for number in green_laps if stop_lap < number <= last_after),
        default=None,
    )
    before_time = green_laps.get(before) if before is not None else None
    after_time = green_laps.get(after) if after is not None else None

    if before_time is not None and after_time is not None:
        gain = before_time - after_time
        caveat = (
            f"Lap {before} against lap {after}; not adjusted for traffic, tyre warm-up, "
            "fuel, or track evolution."
        )
    else:
        gain = None
        # Where the laps were looked for, exactly: the window after the stop
        # is counted from the out-lap, and stops short of the driver's next
        # stop. "Within 3 laps after the stop" was said of Ocon in the 2025
        # Qatar GP, who stopped on laps 8 and 9 and ran a clean lap 11.
        if next_stop_lap is not None and next_stop_lap - 1 < stop_lap + 1 + window:
            after_the_stop = f"after the out-lap and before the next stop, on lap {next_stop_lap}"
        else:
            after_the_stop = f"in the {window} laps after the out-lap"
        missing = " or ".join(
            where
            for where, lap_time in (
                (f"in the {window} laps before the in-lap", before_time),
                (after_the_stop, after_time),
            )
            if lap_time is None
        )
        caveat = f"No clean green-flag lap {missing}, so no pace change is reported."
    return {
        "driver_code": driver,
        "stop_lap": stop_lap,
        "first_clean_lap_gain_ms": gain,
        "before_lap_number": before,
        "before_lap_ms": before_time,
        "after_lap_number": after,
        "after_lap_ms": after_time,
        "caveat": caveat,
    }


def _green_lap_times(laps: list[dict[str, Any]]) -> dict[str, dict[int, float]]:
    """Clean laps run entirely under green, as lap number -> lap time per driver."""
    output: dict[str, dict[int, float]] = defaultdict(dict)
    for lap in clean_laps(laps):
        number = lap_number(lap)
        if number is None or has_yellow(lap.get("track_status")):
            continue
        output[_driver(lap)][number] = lap["lap_time_ms"]
    return output


def _is_green(lap: dict[str, Any]) -> bool:
    status = lap.get("track_status")
    return not is_neutralized(status) and not has_yellow(status)


def _driver(row: dict[str, Any]) -> str:
    return str(row.get("driver_code") or "").upper()


def _rounded(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
