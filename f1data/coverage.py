"""Measure what a fetched session actually holds, feed by feed.

FastF1 reports a session as loaded when the timing table is not empty. A feed
that F1 refused, or answered in part, leaves an empty or short table behind and
no error (docs/architecture-review-findings.md, AR-21). The figures here are
taken from the samples as fetched, before any interpolation or thinning, so
that "one sample per lap" cannot pass for telemetry.

Measuring and judging are separate. ``measure_coverage`` records counts and is
stored with the snapshot; ``evaluate_coverage`` applies the bars and can change
without a re-fetch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES, circuit_corner_count, parse_pit_stop_series
from f1data.loaded import driver_codes, present

# What a measurement records. A snapshot measured by an older version says
# nothing about a feed added since, and is fetched again (f1data/due.py).
#
#   2  the pit-stop feed and the circuit information; tyre age counted
#      apart from compound and stint
#
# The number goes up when a fetch starts collecting something it did not
# before, because only another fetch can supply it. A figure that can be
# worked out from what is already archived is added without a new number, and
# read as optional: ``circuit_corners`` is one, the laps on which a feed
# repeats itself are two more, and the laps a feed can be relied on for are
# another two. A build counts those from the feeds it has
# loaded and writes them beside the snapshot before it publishes anything
# (``write_remeasurement`` in f1data/archive.py), for the snapshot it took
# and for every other of the session whose record lacks them.
MEASUREMENT_VERSION = 2

# A lap's telemetry is usable when its samples reach from the start of the lap
# to its end with no hole longer than this. F1 sends car and position data
# about every 0.24 s; the longest hole inside any lap of the 2026 Austrian GP
# (1,339 laps, session key 11315) was 1.64 s.
MAX_SAMPLE_GAP_SECONDS = 5.0

# A feed can arrive on time and say nothing: the sample before, sent again.
# From lap 7 of the 2026 Hungarian GP the car feed does that most of the time
# for nearly every car, and from lap 15 the position feed does; the samples
# are a quarter of a second apart as they should be, so no hole is seen. The
# speed stands still, the lap measures anywhere from 1,745 to 5,214 m, and
# the car stands still on the map and then jumps.
#
# A car sample repeats when it has the engine speed and the road speed of the
# sample before; a position sample when it has the place of the one before.
# Only samples of a car that is moving are counted, since one standing in its
# pit box repeats itself truthfully. Counted so over the nine races of 2026
# from Australia to Britain (10,406 laps): on a lap where nothing is wrong
# fewer than one car sample in a hundred repeats, and the worst lap of the
# Monaco, Canadian and Austrian races has 5, 12 and 11 in a hundred. Japan
# has 167 laps over a quarter and China 132.
MOVING_ABOVE_KPH = 30.0
# A lap repeats itself when more than this share of its moving samples do.
MAX_REPEATED_SHARE_OF_A_LAP = 0.25
# A lap with fewer moving samples than this is not judged either way: a lap
# spent stopped under a red flag, or one the feed has almost nothing of,
# which is the other bars' to say.
MIN_MOVING_SAMPLES_TO_JUDGE_A_LAP = 10
# Whether a car is moving is not the car feed's alone to say. A car feed that
# sends a speed of nought again and again has the car standing, and was
# believed: none of those samples was counted, for the car feed or for the
# position feed beside it. Two things can say otherwise.
#
# The position feed, where it has the car at two places close enough in time
# and far enough apart.
MAX_SECONDS_BETWEEN_PLACES = 1.0
# And the timing, which neither feed can take with it. A lap has room for
# standing in what it took beyond the fastest lap of the session, since no car
# gets round in less; the time a feed has the car standing beyond that room,
# and this much more for the walking pace of a pit box, was not stood. Over
# the same nine races no lap has a car standing for longer than the lap had
# room for, this margin left out. The nearest is a first lap with 2.1 s to
# spare; the lap of the Monaco GP that the red flag is in, 2,264 s long with
# the car standing for 2,137 of them, has 54 s.
#
# What neither sees: both feeds stopped together for less time than the lap
# had room for, as on a lap behind the safety car.
STANDING_MARGIN_SECONDS = 5.0
CAR_REPEATS_BAR = "car_data_repeats"
POSITION_REPEATS_BAR = "position_repeats"

CAR_CHANNELS = ("Speed", "Throttle", "Brake", "nGear", "RPM")
POSITION_CHANNELS = ("X", "Y")
# What FastF1 writes in ``Source`` for a sample that came from F1's car or position feed.
_FEED_SOURCES = ("car", "pos")

# Share of a driver's expected laps that must be usable, per feed.
MIN_CAR_LAP_SHARE = 0.95
MIN_POSITION_LAP_SHARE = 0.95
MIN_TYRE_LAP_SHARE = 0.95
# Timing has no tolerance: a driver has to have every lap they are classified
# with. Across the 21 races and sprints of 2026 fetched on 2026-10-06 (462
# driver entries) timing had exactly the classified laps 452 times and one lap
# more, for a retirement, 10 times. It never had fewer. A tolerance of one lap
# would let a driver classified with one lap pass with no data at all.

# The F1 feed (or other source) each bar depends on, by the name it is fetched
# under. Used to tell "F1 does not hold this" from "this did not arrive whole".
FEED_FILE_BY_BAR = {
    "session_info": "SessionInfo.jsonStream",
    "driver_list": "DriverList.jsonStream",
    "timing_data": "TimingData.jsonStream",
    "tyre_data": "TimingAppData.jsonStream",
    "track_status": "TrackStatus.jsonStream",
    "lap_count": "LapCount.jsonStream",
    "session_status": "SessionStatus.jsonStream",
    "weather": "WeatherData.jsonStream",
    "race_control": "RaceControlMessages.jsonStream",
    "car_data": "CarData.z.jsonStream",
    "position": "Position.z.jsonStream",
    "pit_stop_series": PIT_STOP_SERIES,
    "circuit_info": CIRCUIT_INFO,
}
_NOT_HELD_STATUSES = frozenset({403, 404})
# Bars whose feed has no entry of its own under ``feeds``, and the per-driver
# figure that shows whether anything of it arrived.
_FIGURE_OF_A_FEED_WITH_NO_ENTRY = {"tyre_data": "tyre_laps", "driver_list": "in_driver_list"}
# What a measurement holds per driver that does not come from F1's feeds, or
# is no bar: the classification of the day, and laps FastF1 made up.
_NOT_OF_THE_FEEDS = frozenset({"classified_laps", "generated_laps"})
# Every count a measurement holds, for the session and for each driver.
_SESSION_COUNTS = (
    "measurement_version",
    "pit_stops_in_timing",
    "pit_stops_in_series",
    "circuit_corners",
    "total_laps",
)
_DRIVER_COUNTS = (
    "classified_laps",
    "timing_laps",
    "generated_laps",
    "car_laps",
    "position_laps",
    "tyre_laps",
    "tyre_age_laps",
    "car_repeating_laps",
    "position_repeating_laps",
    "car_reliable_laps",
    "position_reliable_laps",
)

# The counts among those that a fetch did not always take, and a build does.
_COUNTED_BY_A_BUILD = (
    "car_repeating_laps",
    "position_repeating_laps",
    "car_reliable_laps",
    "position_reliable_laps",
)

RACE_LIKE_SESSION_TYPES = frozenset({"R", "S"})
CLASSIFICATION_BAR = "classification"
REMEASURE_BAR = "measurement"
_ENDED_STATUSES = frozenset({"Finished", "Finalised", "Ends"})
_UNKNOWN_COMPOUNDS = frozenset({"", "NONE", "NAN", "UNKNOWN"})


@dataclass(frozen=True)
class Shortfall:
    """One bar a session does not meet."""

    bar: str
    driver: str | None
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {"bar": self.bar, "driver": self.driver, "detail": self.detail}


def measure_coverage(
    session: Any, session_type: str, extras: dict[str, bytes] | None = None
) -> dict[str, Any]:
    """Count what arrived for a loaded FastF1 session.

    ``session_type`` is the short code (``R``, ``S``, ...). ``extras`` are the
    feeds FastF1 does not load, by name. The result is plain JSON and carries
    no judgement.
    """
    extras = extras or {}
    laps = _frame(session, "laps")
    results = _frame(session, "results")
    car_data = _mapping(session, "car_data")
    position_data = _mapping(session, "pos_data")

    fastest_lap = _fastest_lap_seconds(laps[~_generated(laps)] if len(laps) else laps)
    drivers: dict[str, dict[str, Any]] = {}
    for number, code in driver_codes(results, laps).items():
        driver_laps = _driver_laps(laps, number)
        timed = driver_laps[~_generated(driver_laps)] if len(driver_laps) else driver_laps
        car_usable = _usable_laps(timed, car_data.get(number), CAR_CHANNELS, _car_valid)
        position_usable = _usable_laps(timed, position_data.get(number), POSITION_CHANNELS, _position_valid)
        car_repeating, position_repeating = _repeating_laps(
            timed, car_data.get(number), position_data.get(number), fastest_lap
        )
        drivers[code] = {
            "number": number,
            "in_driver_list": _in_driver_list(results, number),
            "classified_laps": _classified_laps(results, number),
            "timing_laps": int(len(timed)),
            "generated_laps": int(len(driver_laps) - len(timed)),
            "car_laps": int(car_usable.sum()),
            "position_laps": int(position_usable.sum()),
            "tyre_laps": _tyre_laps(timed),
            "tyre_age_laps": _tyre_laps(timed, with_age=True),
            "car_repeating_laps": int(car_repeating.sum()),
            "position_repeating_laps": int(position_repeating.sum()),
            # A lap can have a hole in it and repeat itself too. It is one
            # lap that cannot be relied on, and is counted here as one.
            "car_reliable_laps": int((car_usable & ~car_repeating).sum()),
            "position_reliable_laps": int((position_usable & ~position_repeating).sum()),
        }

    session_info = _safe_attr(session, "session_info") or {}
    return {
        "measurement_version": MEASUREMENT_VERSION,
        "max_sample_gap_seconds": MAX_SAMPLE_GAP_SECONDS,
        "session_type": session_type.upper(),
        "session_key": session_info.get("Key"),
        "feeds": {
            "session_info": bool(session_info.get("Key")),
            "timing_data": len(laps) > 0,
            "car_data": len(car_data) > 0,
            "position": len(position_data) > 0,
            "weather": len(_frame(session, "weather_data")) > 0,
            "race_control": len(_frame(session, "race_control_messages")) > 0,
            "track_status": len(_frame(session, "track_status")) > 0,
            "session_status": len(_frame(session, "session_status")) > 0,
            "lap_count": _safe_attr(session, "total_laps") is not None,
            "pit_stop_series": PIT_STOP_SERIES in extras,
            "circuit_info": CIRCUIT_INFO in extras,
        },
        # Stops as the timing saw them and as the pit-stop feed reported them.
        # A session nobody pitted in has no pit-stop feed to miss.
        "pit_stops_in_timing": _pit_stops_in_timing(laps),
        "pit_stops_in_series": len(parse_pit_stop_series(extras.get(PIT_STOP_SERIES, b""))),
        "circuit_corners": circuit_corner_count(extras.get(CIRCUIT_INFO, b"")),
        "session_ended": _session_ended(_frame(session, "session_status")),
        "total_laps": _int_or_none(_safe_attr(session, "total_laps")),
        "drivers": drivers,
    }


def evaluate_coverage(measurement: dict[str, Any]) -> list[Shortfall]:
    """Return every bar the measured session falls short of. Empty means complete."""
    shortfalls: list[Shortfall] = []
    feeds = measurement.get("feeds", {})
    race_like = measurement.get("session_type") in RACE_LIKE_SESSION_TYPES

    for feed in ("session_info", "timing_data", "weather", "race_control", "track_status", "session_status"):
        if not feeds.get(feed):
            shortfalls.append(Shortfall(feed, None, "feed did not arrive"))
    if race_like and not feeds.get("lap_count"):
        shortfalls.append(Shortfall("lap_count", None, "feed did not arrive"))
    if feeds.get("session_status") and not measurement.get("session_ended"):
        shortfalls.append(Shortfall("session_status", None, "feed does not show the session ended"))
    if int(measurement.get("measurement_version") or 1) < MEASUREMENT_VERSION:
        # An older measurement did not count what today's bars ask about, and
        # a count that is absent is not a count of zero. Say so, and let the
        # snapshot rank below any that was measured in full.
        shortfalls.append(Shortfall(REMEASURE_BAR, None, "measured before the current bars existed"))
    # The bar is that the feed arrived with at least one stop it can vouch
    # for. The two counts are not compared: the timing counts every entry to
    # the pit lane, and across the 21 sessions of 2026 the feed held between
    # 25% (Monza, 8 of 32) and 100% of them.
    entries = int(measurement.get("pit_stops_in_timing") or 0)
    if race_like and entries and not measurement.get("pit_stops_in_series"):
        # Entries, and not stops: of the 20 in the 2025 Sao Paulo sprint, 18
        # are cars that waited in the pit lane through a red flag and one
        # went through without stopping.
        shortfalls.append(
            Shortfall(
                "pit_stop_series",
                None,
                "no stationary time from F1's pit-stop feed, and the timing has "
                f"{entries} {'entry' if entries == 1 else 'entries'} to the pit lane",
            )
        )
    # The corner analysis can fall back to inferring corners from braking, so
    # a build does not fail without this. It is still a bar: with it missing
    # the session shows inferred corners, and a later fetch may well get it.
    #
    # A count that is absent is not a count that passes. Snapshots measured
    # before corners were counted have theirs filled in from the archived
    # file when they are listed (f1data/archive.py).
    if not measurement.get("circuit_corners"):
        shortfalls.append(Shortfall("circuit_info", None, "corner positions did not arrive"))

    drivers = measurement.get("drivers", {})
    if not drivers:
        shortfalls.append(Shortfall("driver_list", None, "no drivers"))

    for code, driver in sorted(drivers.items()):
        if not driver.get("in_driver_list"):
            shortfalls.append(Shortfall("driver_list", code, "driver is missing from F1's driver list"))

        classified = driver.get("classified_laps")
        timing = int(driver.get("timing_laps") or 0)
        if race_like and classified is None:
            # Jolpica can be hours behind a race. The session cannot be called
            # complete without it, but the feeds can still be judged against
            # the laps that were timed, which is what tells a fetch whether
            # asking F1 again could help.
            shortfalls.append(Shortfall(CLASSIFICATION_BAR, code, "no classified lap count"))
            expected = timing
        elif race_like:
            expected = int(classified)
            if timing < expected:
                shortfalls.append(
                    Shortfall("timing_data", code, f"{timing} timing laps for {expected} classified")
                )
        else:
            # No lap count to compare with; a driver in the result has to have laps.
            expected = timing
            if timing == 0:
                shortfalls.append(Shortfall("timing_data", code, "no timing laps"))

        if expected <= 0:
            continue
        short: set[str] = set()
        for bar, key, minimum in (
            ("car_data", "car_laps", MIN_CAR_LAP_SHARE),
            ("position", "position_laps", MIN_POSITION_LAP_SHARE),
            ("tyre_data", "tyre_laps", MIN_TYRE_LAP_SHARE),
        ):
            usable = int(driver.get(key) or 0)
            if usable < math.ceil(minimum * expected):
                short.add(bar)
                shortfalls.append(
                    Shortfall(bar, code, f"{usable} of {expected} expected laps usable")
                )
        # The same tolerance from the other side: as many laps may repeat
        # themselves as may be missing. A count that is absent was never
        # taken, by a fetch from before it was counted, and says nothing: the
        # build that reads such a snapshot counts it before it publishes.
        allowed = expected - math.ceil(MIN_CAR_LAP_SHARE * expected)
        for bar, key, feed, what in (
            (CAR_REPEATS_BAR, "car_repeating_laps", "car feed", "speed, pedals and gear"),
            (POSITION_REPEATS_BAR, "position_repeating_laps", "position feed", "place on the track"),
        ):
            repeating = driver.get(key)
            if repeating is not None and int(repeating) > allowed:
                short.add(bar)
                shortfalls.append(
                    Shortfall(
                        bar,
                        code,
                        f"F1's {feed} repeats itself on {int(repeating)} of {expected} expected laps, "
                        f"whose {what} cannot be relied on",
                    )
                )
        # The two tolerances are not one each to spend. A feed with as many
        # laps missing as may be, and as many others repeating as may, passes
        # both bars above with twice as many laps as either allows that
        # cannot be relied on. The laps that can be are held to the share the
        # usable ones are, under the feed's own bar, where neither bar above
        # has said the feed is short already: said twice, one feed short
        # would count as two in the order of snapshots. Absent, the count
        # says nothing, like the one above.
        for bar, repeats, feed, minimum in (
            ("car_data", CAR_REPEATS_BAR, "car", MIN_CAR_LAP_SHARE),
            ("position", POSITION_REPEATS_BAR, "position", MIN_POSITION_LAP_SHARE),
        ):
            reliable = driver.get(f"{feed}_reliable_laps")
            if reliable is None or short & {bar, repeats}:
                continue
            if int(reliable) < math.ceil(minimum * expected):
                usable = int(driver.get(f"{feed}_laps") or 0)
                shortfalls.append(
                    Shortfall(
                        bar,
                        code,
                        f"{int(reliable)} of {expected} expected laps can be relied on: {usable} are usable, "
                        f"and F1's {feed} feed repeats itself on {usable - int(reliable)} of those",
                    )
                )
    return shortfalls


def counted_in_full(measurement: dict[str, Any]) -> bool:
    """Whether the record has every count a build works out from the feeds, for every driver.

    The laps a feed repeats itself on and the laps it can be relied on for
    were not counted by the first fetches. A record without them is judged
    without them, which is a guess: nothing held against it for the first,
    every lap that repeats taken off for the second.
    """
    return all(
        driver.get(key) is not None
        for driver in measurement.get("drivers", {}).values()
        for key in _COUNTED_BY_A_BUILD
    )


def is_measurement(measurement: Any) -> bool:
    """Whether this is a measurement in every figure, whether or not anything reads it today.

    Checked figure by figure, not by running what reads a measurement: the
    readers skip the counts of a driver with no laps to account for, and read
    them on the day a result gives that driver laps. A count may be missing,
    as it is in a record from before it was counted. It may not be text, a
    fraction, negative, or true and false.
    """

    def count(value: Any) -> bool:
        return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)

    def flag(value: Any) -> bool:
        return value is None or isinstance(value, bool)

    if not isinstance(measurement, dict):
        return False
    feeds, drivers = measurement.get("feeds"), measurement.get("drivers")
    if not isinstance(feeds, dict) or not isinstance(drivers, dict):
        return False
    if not all(isinstance(name, str) and isinstance(arrived, bool) for name, arrived in feeds.items()):
        return False
    if not isinstance(measurement.get("session_type"), str) or not flag(measurement.get("session_ended")):
        return False
    if not all(count(measurement.get(key)) for key in _SESSION_COUNTS):
        return False
    for code, driver in drivers.items():
        if not isinstance(code, str) or not isinstance(driver, dict):
            return False
        number = driver.get("number")
        if isinstance(number, bool) or not isinstance(number, (str, int)):
            return False
        if not flag(driver.get("in_driver_list")) or not all(count(driver.get(key)) for key in _DRIVER_COUNTS):
            return False
    return True


def apply_classification(measurement: dict[str, Any], classified_laps: dict[str, int]) -> dict[str, Any]:
    """The measurement with each driver's classified lap count taken from today's result.

    ``classified_laps`` maps a driver number to the laps Jolpica classifies the
    driver with, and must be the whole result, not part of one. A snapshot
    records the classification as it stood when it was fetched, which may be
    nothing at all; a session is judged against the one of today. A classified
    driver the fetch never saw is added with nothing to their name, so that
    their absence is a shortfall and not an omission.
    """
    by_number = {str(number): int(laps) for number, laps in classified_laps.items()}
    drivers: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for code, driver in measurement.get("drivers", {}).items():
        number = str(driver.get("number"))
        seen.add(number)
        # The result of today is the whole answer. A driver it does not list
        # is not classified, so has no laps to account for; what the snapshot
        # recorded for them, a count or the lack of one, no longer applies.
        drivers[code] = {**driver, "classified_laps": by_number.get(number, 0)}
    for number, laps in sorted(by_number.items()):
        if number not in seen:
            drivers[f"#{number}"] = {
                "number": number,
                "in_driver_list": False,
                "classified_laps": laps,
                "timing_laps": 0,
                "generated_laps": 0,
                "car_laps": 0,
                "position_laps": 0,
                "tyre_laps": 0,
                "tyre_age_laps": 0,
                "car_repeating_laps": 0,
                "position_repeating_laps": 0,
                "car_reliable_laps": 0,
                "position_reliable_laps": 0,
            }
    return {**measurement, "drivers": drivers}


def feed_figures(measurement: dict[str, Any]) -> dict[str, Any]:
    """What a measurement says of the feeds, and nothing of the classification.

    Two measurements of the same archived feeds by the same code agree on
    this, whenever they are taken. They need not agree on the rest: the laps
    a driver is classified with come from Jolpica as it stood that day, and a
    driver known from the result alone is there or not with the result.
    """
    drivers = {}
    for driver in measurement.get("drivers", {}).values():
        if not (driver.get("in_driver_list") or driver.get("timing_laps") or driver.get("generated_laps")):
            continue
        drivers[str(driver.get("number"))] = {
            key: value for key, value in driver.items() if key not in _NOT_OF_THE_FEEDS
        }
    return {**{key: value for key, value in measurement.items() if key != "drivers"}, "drivers": drivers}


def feed_is_absent(measurement: dict[str, Any], bar: str) -> bool:
    """Whether the feed behind ``bar`` is missing outright, for every driver."""
    feeds = measurement.get("feeds", {})
    if bar in feeds:
        return not feeds[bar]
    figure = _FIGURE_OF_A_FEED_WITH_NO_ENTRY.get(bar)
    if figure is None:
        return False
    return not any(driver.get(figure) for driver in measurement.get("drivers", {}).values())


def f1_does_not_hold(
    shortfall: Shortfall, feed_status: dict[str, Any], measurement: dict[str, Any]
) -> bool:
    """Whether the feed behind a shortfall is one F1 answered that it does not have.

    F1 answers 403 for a feed that is not in a session's archive, as it does
    for the pit-stop feed of races before late 2024. A feed that was answered
    and came up short is a different thing: it may yet be mended.

    ``measurement`` is the one the shortfall was found in.
    """
    # Only a feed that is missing outright can be one F1 does not hold. One
    # that arrived and is short came from somewhere: short for a driver, or
    # as a whole, like a session status that never reaches the end or a
    # pit-stop feed with no stop in it. FastF1 asks its mirror when F1
    # refuses, so F1's refusal and the feed's arrival can sit side by side in
    # one fetch. A feed that is absent for everyone shows as a shortfall for
    # each driver, and those count here like any other.
    if not feed_is_absent(measurement, shortfall.bar):
        return False
    # A refusal looks the same as an absence, one feed at a time. It counts as
    # an absence only from a fetch F1 was otherwise answering: the plan asks
    # for "a fetch from a network F1 answers" (criterion 1).
    if feed_status.get(FEED_FILE_BY_BAR["session_info"]) != 200:
        return False
    answered = feed_status.get(FEED_FILE_BY_BAR.get(shortfall.bar, ""))
    return isinstance(answered, int) and not isinstance(answered, bool) and answered in _NOT_HELD_STATUSES


def refetch_could_help(shortfalls: list[Shortfall]) -> bool:
    """Whether any shortfall is one that asking F1 again might cure.

    A missing classification is Jolpica's to supply, not F1's.
    """
    return any(shortfall.bar != CLASSIFICATION_BAR for shortfall in shortfalls)


def _lap_counts(measurement: dict[str, Any]) -> list[tuple[int, int]]:
    """For each driver and each per-lap feed, the laps that can be relied on and the laps expected.

    A lap a feed repeats itself on arrived on time and is counted among the
    feed's usable laps, and cannot be relied on. ``car_reliable_laps`` and
    ``position_reliable_laps`` are the usable laps without those. A record
    from before they were counted has the usable laps and the laps that
    repeat and not how many are both, so every lap that repeats is taken off
    the usable ones: too few for a lap with a hole in it as well, never too
    many. A count of laps that repeat that is absent was never taken and
    takes nothing off. Too few can still pick the wrong one of two snapshots,
    so a build counts them for every snapshot of a session before it takes
    one (``Builder.build``).
    """
    race_like = measurement.get("session_type") in RACE_LIKE_SESSION_TYPES
    counts: list[tuple[int, int]] = []
    for driver in measurement.get("drivers", {}).values():
        timing = int(driver.get("timing_laps") or 0)
        classified = driver.get("classified_laps")
        expected = int(classified) if race_like and classified is not None else timing
        if expected <= 0:
            continue
        laps = [timing, int(driver.get("tyre_laps") or 0)]
        for feed in ("car", "position"):
            reliable = driver.get(f"{feed}_reliable_laps")
            if reliable is None:
                reliable = int(driver.get(f"{feed}_laps") or 0) - int(driver.get(f"{feed}_repeating_laps") or 0)
            laps.append(int(reliable))
        counts.extend((min(max(count, 0), expected), expected) for count in laps)
    return counts


def weakest_share(measurement: dict[str, Any]) -> float:
    """Lowest share of laps to be relied on for any driver on any per-lap feed, between 0 and 1.

    Used to order two snapshots that both fall short (section 6, rule 6).
    """
    return min((laps / expected for laps, expected in _lap_counts(measurement)), default=1.0)


def overall_share(measurement: dict[str, Any]) -> float:
    """The share of laps to be relied on over every driver and every per-lap feed, between 0 and 1.

    Used to order two snapshots the weakest share cannot tell apart: it is
    one driver's on one feed, and says nothing of how the rest fared.
    """
    counts = _lap_counts(measurement)
    expected = sum(expected for _, expected in counts)
    return sum(laps for laps, _ in counts) / expected if expected else 1.0


def repeating_laps(measurement: dict[str, Any]) -> int:
    """The laps on which F1's car feed or position feed repeats itself, over every driver.

    Used to order two snapshots with as many laps to be relied on: a lap
    that is missing says so, and one that repeats itself does not.
    """
    return sum(
        int(driver.get(key) or 0)
        for driver in measurement.get("drivers", {}).values()
        for key in ("car_repeating_laps", "position_repeating_laps")
    )


def lap_is_usable(sample_times: np.ndarray, lap_start: float, lap_end: float) -> bool:
    """Whether sorted ``sample_times`` (seconds) cover one lap without a long hole."""
    if not (np.isfinite(lap_start) and np.isfinite(lap_end)) or lap_end <= lap_start:
        return False
    first = int(np.searchsorted(sample_times, lap_start, side="left"))
    last = int(np.searchsorted(sample_times, lap_end, side="right"))
    if last - first < 2:
        return False
    window = sample_times[first:last]
    edges = np.concatenate(([lap_start], window, [lap_end]))
    return bool(np.diff(edges).max() <= MAX_SAMPLE_GAP_SECONDS)


def _usable_laps(laps: pd.DataFrame, telemetry: Any, channels: tuple[str, ...], valid: Any) -> np.ndarray:
    """Which of ``laps`` the feed covers without a long hole, lap by lap."""
    none = np.zeros(len(laps), dtype=bool)
    if telemetry is None or len(laps) == 0 or len(telemetry) == 0:
        return none
    if any(channel not in telemetry.columns for channel in channels) or "SessionTime" not in telemetry.columns:
        return none
    mask = valid(telemetry)
    times = _seconds(telemetry["SessionTime"])[mask]
    times = np.sort(times[np.isfinite(times)])
    starts = _seconds(laps["LapStartTime"])
    ends = _seconds(laps["Time"])
    return np.array([lap_is_usable(times, start, end) for start, end in zip(starts, ends)], dtype=bool)


def _repeating_laps(
    laps: pd.DataFrame, car: Any, position: Any, fastest_lap: float
) -> tuple[np.ndarray, np.ndarray]:
    """Which of ``laps`` the car feed repeats itself on, and which the position feed, lap by lap.

    A sample is counted when the car is moving. The car feed says so with its
    speed, for both: a position sample is the car's at the speed of the car
    sample before it. Where the car feed has the car standing, the position
    feed may have it moving, and a lap has only so long to stand in: what it
    took beyond ``fastest_lap`` seconds. Without a car feed neither is
    counted, and the bar on car data says what is wrong.
    """
    none = np.zeros(len(laps), dtype=bool)
    if car is None or len(laps) == 0 or len(car) == 0:
        return none, none
    if any(channel not in car.columns for channel in CAR_CHANNELS) or "SessionTime" not in car.columns:
        return none, none
    times, (speed, engine) = _in_order(car, _car_valid(car), ("Speed", "RPM"))
    moving = speed > MOVING_ABOVE_KPH
    starts, ends = _seconds(laps["LapStartTime"]), _seconds(laps["Time"])
    rooms = ends - starts - fastest_lap

    if position is None or len(position) == 0 or len(times) == 0:
        return _laps_that_repeat(times, moving, _same_as_before(speed, engine), starts, ends, rooms), none
    if any(channel not in position.columns for channel in POSITION_CHANNELS) or "SessionTime" not in position.columns:
        return _laps_that_repeat(times, moving, _same_as_before(speed, engine), starts, ends, rooms), none
    placed_at, (x, y) = _in_order(position, _position_valid(position), POSITION_CHANNELS)
    car_laps = _laps_that_repeat(
        times, moving | _seen_to_move(times, placed_at, x, y), _same_as_before(speed, engine), starts, ends, rooms
    )
    before = np.clip(np.searchsorted(times, placed_at, side="right") - 1, 0, len(times) - 1)
    return car_laps, _laps_that_repeat(placed_at, moving[before], _same_as_before(x, y), starts, ends, rooms)


def _fastest_lap_seconds(laps: pd.DataFrame) -> float:
    """The quickest lap any driver was timed on, or NaN where no lap has both its ends."""
    if len(laps) == 0 or not {"LapStartTime", "Time"} <= set(laps.columns):
        return math.nan
    taken = _seconds(laps["Time"]) - _seconds(laps["LapStartTime"])
    taken = taken[np.isfinite(taken) & (taken > 0)]
    return float(taken.min()) if len(taken) else math.nan


def _in_order(
    telemetry: pd.DataFrame, valid: np.ndarray, channels: tuple[str, ...]
) -> tuple[np.ndarray, list[np.ndarray]]:
    """The session times of the valid samples that have one, in order, and ``channels`` beside them."""
    times = _seconds(telemetry["SessionTime"])
    keep = valid & np.isfinite(times)
    order = np.argsort(times[keep], kind="stable")
    return times[keep][order], [
        pd.to_numeric(telemetry[channel], errors="coerce").to_numpy(dtype=float)[keep][order]
        for channel in channels
    ]


def _same_as_before(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    same = np.zeros(len(first), dtype=bool)
    same[1:] = (first[1:] == first[:-1]) & (second[1:] == second[:-1])
    return same


def _seen_to_move(times: np.ndarray, placed_at: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """At which of ``times`` the position feed has the car moving.

    From the place before the time to the place at or after it, where the
    feed has both and they are not far apart in time. F1 gives a place in
    tenths of a metre.
    """
    if len(placed_at) < 2:
        return np.zeros(len(times), dtype=bool)
    after = np.searchsorted(placed_at, times, side="left")
    between = (after > 0) & (after < len(placed_at))
    after = np.clip(after, 1, len(placed_at) - 1)
    seconds = placed_at[after] - placed_at[after - 1]
    metres = np.hypot(x[after] - x[after - 1], y[after] - y[after - 1]) / 10.0
    near = (seconds > 0) & (seconds <= MAX_SECONDS_BETWEEN_PLACES)
    return between & near & (metres * 3.6 > MOVING_ABOVE_KPH * seconds)


def _laps_that_repeat(
    times: np.ndarray,
    moving: np.ndarray,
    repeats: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    rooms: np.ndarray,
) -> np.ndarray:
    found = np.zeros(len(starts), dtype=bool)
    for lap, (start, end, room) in enumerate(zip(starts, ends, rooms)):
        if not (np.isfinite(start) and np.isfinite(end)) or end <= start:
            continue
        first = int(np.searchsorted(times, start, side="left"))
        last = int(np.searchsorted(times, end, side="right"))
        going, same = moving[first:last], repeats[first:last]
        judged = float(going.sum())
        repeated = float((same & going).sum())
        # A car that was not standing was moving, and what the feed sent of
        # it then is judged like the rest.
        not_stood = _share_not_stood(times[first:last], going, start, room)
        if not_stood:
            judged += not_stood * float((~going).sum())
            repeated += not_stood * float((same & ~going).sum())
        if judged < MIN_MOVING_SAMPLES_TO_JUDGE_A_LAP:
            continue
        found[lap] = repeated > MAX_REPEATED_SHARE_OF_A_LAP * judged
    return found


def _share_not_stood(times: np.ndarray, going: np.ndarray, start: float, room: float) -> float:
    """The share of the time a feed has a car standing in a lap that the lap had no room for.

    ``room`` is what the lap took beyond the fastest lap of the session. A
    hole in the feed is standing only for as long as a hole may be.
    """
    if not np.isfinite(room):
        return 0.0
    since = np.minimum(np.diff(times, prepend=start), MAX_SAMPLE_GAP_SECONDS)
    standing = float(since[~going].sum())
    could = max(float(room), 0.0) + STANDING_MARGIN_SECONDS
    return (standing - could) / standing if standing > could else 0.0


def sent_by_f1(telemetry: pd.DataFrame) -> np.ndarray:
    """Which rows of a FastF1 car or position table are samples F1 sent.

    When a car is missing from part of a feed, FastF1 gives it a row for
    every timestamp any other car has and fills the channels with zeros. In
    the 2026 Belgian GP every car has seven such rows; in the Spanish GP some
    have hundreds. Zero speed and zero RPM in the middle of a lap are not a
    measurement. FastF1 marks its own rows in one way only: a row from a feed
    has ``car`` or ``pos`` for its ``Source`` and a row it added has none.
    Loading a session then turns the column to text, so that on a loaded
    session the missing one reads ``"nan"``. A row is F1's when it names its
    feed, whatever else the column may come to hold.
    """
    if "Source" not in telemetry.columns:
        return np.ones(len(telemetry), dtype=bool)
    return telemetry["Source"].isin(_FEED_SOURCES).to_numpy()


def _car_valid(telemetry: pd.DataFrame) -> np.ndarray:
    return telemetry[list(CAR_CHANNELS)].notna().all(axis=1).to_numpy() & sent_by_f1(telemetry)


def _position_valid(telemetry: pd.DataFrame) -> np.ndarray:
    # F1 sends (0, 0) while it has no position for a car, such as before it
    # leaves the garage. Those samples are not positions.
    present = telemetry[list(POSITION_CHANNELS)].notna().all(axis=1)
    located = (telemetry["X"] != 0) | (telemetry["Y"] != 0)
    return (present & located).to_numpy() & sent_by_f1(telemetry)


def _pit_stops_in_timing(laps: pd.DataFrame) -> int:
    if len(laps) == 0 or "PitInTime" not in laps.columns:
        return 0
    return int((laps["PitInTime"].notna() & ~_generated(laps)).sum())


def _tyre_laps(laps: pd.DataFrame, with_age: bool = False) -> int:
    """Laps whose compound and stint are known, and whose tyre age is too if asked.

    The bar is on compound and stint. When a driver's TimingAppData is missing
    FastF1 leaves the compound empty, and that is what a second fetch can
    cure. Tyre age is counted apart and is not a bar: F1 does not report the
    age of a set that went on used, so those laps have a compound, a stint and
    no age however often they are fetched. In the 2026 Barcelona race that is
    21 of Bearman's 60 laps, and in the 2026 race at Sepang it is 152 laps
    across eleven drivers.
    """
    if len(laps) == 0 or not {"Compound", "Stint"} <= set(laps.columns):
        return 0
    compound = laps["Compound"].astype("string").str.strip().str.upper()
    known = compound.notna() & ~compound.isin(_UNKNOWN_COMPOUNDS) & laps["Stint"].notna()
    if with_age:
        if "TyreLife" not in laps.columns:
            return 0
        known = known & laps["TyreLife"].notna()
    return int(known.sum())


def _driver_laps(laps: pd.DataFrame, number: str) -> pd.DataFrame:
    if len(laps) == 0 or "DriverNumber" not in laps.columns:
        return laps.iloc[0:0]
    return laps[laps["DriverNumber"].astype(str) == number]


def _generated(laps: pd.DataFrame) -> pd.Series:
    if "FastF1Generated" not in laps.columns:
        return pd.Series(False, index=laps.index)
    return laps["FastF1Generated"].fillna(False).astype(bool)


def _classified_laps(results: pd.DataFrame, number: str) -> int | None:
    if len(results) == 0 or "Laps" not in results.columns:
        return None
    rows = results[_numbers(results) == number]
    if len(rows) == 0:
        return None
    return _int_or_none(rows["Laps"].iloc[0])


def _in_driver_list(results: pd.DataFrame, number: str) -> bool:
    # ``BroadcastName`` comes only from F1's driver list. When that feed fails
    # FastF1 fills the result from Jolpica alone and leaves it empty.
    if len(results) == 0 or "BroadcastName" not in results.columns:
        return False
    rows = results[_numbers(results) == number]
    return len(rows) > 0 and _present(rows["BroadcastName"].iloc[0])


def _numbers(results: pd.DataFrame) -> pd.Series:
    if "DriverNumber" in results.columns:
        return results["DriverNumber"].astype(str)
    return pd.Series(results.index.astype(str), index=results.index)


def _session_ended(session_status: pd.DataFrame) -> bool:
    if len(session_status) == 0 or "Status" not in session_status.columns:
        return False
    return bool(set(session_status["Status"].astype(str)) & _ENDED_STATUSES)


def _seconds(series: pd.Series) -> np.ndarray:
    return pd.to_timedelta(series).dt.total_seconds().to_numpy(dtype=float)


def _frame(session: Any, attribute: str) -> pd.DataFrame:
    value = _safe_attr(session, attribute)
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _mapping(session: Any, attribute: str) -> dict[str, Any]:
    value = _safe_attr(session, attribute)
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _safe_attr(session: Any, attribute: str) -> Any:
    # FastF1 raises DataNotLoadedError for anything a failed feed left unset.
    try:
        return getattr(session, attribute)
    except Exception:
        return None


def _present(value: Any) -> bool:
    # Nothing, or the word FastF1's cast to text makes of nothing, is not a
    # value: a driver list entry with no name in it is not an entry.
    return present(value) and str(value).strip() != ""


def _int_or_none(value: Any) -> int | None:
    if not _present(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
