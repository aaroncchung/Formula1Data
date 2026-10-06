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

from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES, parse_pit_stop_series

# What a measurement records. A snapshot measured by an older version says
# nothing about a feed added since, and is fetched again (f1data/due.py).
#
#   2  the pit-stop feed and the circuit information; tyre age counted
#      apart from compound and stint
MEASUREMENT_VERSION = 2

# A lap's telemetry is usable when its samples reach from the start of the lap
# to its end with no hole longer than this. F1 sends car and position data
# about every 0.24 s; the longest hole inside any lap of the 2026 Austrian GP
# (1,339 laps, session key 11315) was 1.64 s.
MAX_SAMPLE_GAP_SECONDS = 5.0

CAR_CHANNELS = ("Speed", "Throttle", "Brake", "nGear", "RPM")
POSITION_CHANNELS = ("X", "Y")

# Share of a driver's expected laps that must be usable, per feed.
MIN_CAR_LAP_SHARE = 0.95
MIN_POSITION_LAP_SHARE = 0.95
MIN_TYRE_LAP_SHARE = 0.95
# Timing laps a driver may be short of the classified count. FastF1 can leave
# out a first lap it could not time; a cut feed loses far more than one.
TIMING_LAP_TOLERANCE = 1

RACE_LIKE_SESSION_TYPES = frozenset({"R", "S"})
CLASSIFICATION_BAR = "classification"
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

    drivers: dict[str, dict[str, Any]] = {}
    for number, code in _driver_codes(results, laps).items():
        driver_laps = _driver_laps(laps, number)
        timed = driver_laps[~_generated(driver_laps)] if len(driver_laps) else driver_laps
        drivers[code] = {
            "number": number,
            "in_driver_list": _in_driver_list(results, number),
            "classified_laps": _classified_laps(results, number),
            "timing_laps": int(len(timed)),
            "generated_laps": int(len(driver_laps) - len(timed)),
            "car_laps": _usable_laps(timed, car_data.get(number), CAR_CHANNELS, _car_valid),
            "position_laps": _usable_laps(
                timed, position_data.get(number), POSITION_CHANNELS, _position_valid
            ),
            "tyre_laps": _tyre_laps(timed),
            "tyre_age_laps": _tyre_laps(timed, with_age=True),
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
    stops = int(measurement.get("pit_stops_in_timing") or 0)
    if race_like and stops and not measurement.get("pit_stops_in_series"):
        shortfalls.append(
            Shortfall("pit_stop_series", None, f"no stationary times for {stops} stop(s) in the timing")
        )
    # The corner analysis can fall back to inferring corners from braking, so
    # a build does not fail without this. It is still a bar: with it missing
    # the session shows inferred corners, and a later fetch may well get it.
    if not feeds.get("circuit_info"):
        shortfalls.append(Shortfall("circuit_info", None, "corner positions did not arrive"))

    drivers = measurement.get("drivers", {})
    if not drivers:
        shortfalls.append(Shortfall("driver_list", None, "no drivers"))

    for code, driver in sorted(drivers.items()):
        if not driver.get("in_driver_list"):
            shortfalls.append(Shortfall("driver_list", code, "driver is missing from F1's driver list"))

        classified = driver.get("classified_laps")
        timing = int(driver.get("timing_laps") or 0)
        tolerance = 0
        if race_like and classified is None:
            # Jolpica can be hours behind a race. The session cannot be called
            # complete without it, but the feeds can still be judged against
            # the laps that were timed, which is what tells a fetch whether
            # asking F1 again could help.
            shortfalls.append(Shortfall(CLASSIFICATION_BAR, code, "no classified lap count"))
            expected = timing
        elif race_like:
            expected = int(classified)
            tolerance = TIMING_LAP_TOLERANCE
            if timing < expected - tolerance:
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
        for bar, key, minimum in (
            ("car_data", "car_laps", MIN_CAR_LAP_SHARE),
            ("position", "position_laps", MIN_POSITION_LAP_SHARE),
            ("tyre_data", "tyre_laps", MIN_TYRE_LAP_SHARE),
        ):
            usable = int(driver.get(key) or 0)
            # A lap the timing bar forgives cannot then be demanded of the
            # feeds, which are only ever counted over laps that were timed.
            required = math.ceil(minimum * expected) - tolerance
            if usable < required:
                shortfalls.append(
                    Shortfall(bar, code, f"{usable} of {expected} expected laps usable")
                )
    return shortfalls


def apply_classification(measurement: dict[str, Any], classified_laps: dict[str, int]) -> dict[str, Any]:
    """The measurement with each driver's classified lap count taken from today's result.

    ``classified_laps`` maps a driver number to the laps Jolpica classifies the
    driver with. A snapshot records the classification as it stood when it was
    fetched, which may be nothing at all; a session is judged against the one
    of today. A classified driver the fetch never saw is added with nothing to
    their name, so that their absence is a shortfall and not an omission.
    """
    by_number = {str(number): int(laps) for number, laps in classified_laps.items()}
    drivers: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for code, driver in measurement.get("drivers", {}).items():
        number = str(driver.get("number"))
        seen.add(number)
        drivers[code] = {**driver, "classified_laps": by_number.get(number, driver.get("classified_laps"))}
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
            }
    return {**measurement, "drivers": drivers}


def refetch_could_help(shortfalls: list[Shortfall]) -> bool:
    """Whether any shortfall is one that asking F1 again might cure.

    A missing classification is Jolpica's to supply, not F1's.
    """
    return any(shortfall.bar != CLASSIFICATION_BAR for shortfall in shortfalls)


def weakest_share(measurement: dict[str, Any]) -> float:
    """Lowest usable share for any driver on any per-lap feed, between 0 and 1.

    Used to order two snapshots that both fall short (section 6, rule 6).
    """
    race_like = measurement.get("session_type") in RACE_LIKE_SESSION_TYPES
    lowest = 1.0
    for driver in measurement.get("drivers", {}).values():
        timing = int(driver.get("timing_laps") or 0)
        classified = driver.get("classified_laps")
        expected = int(classified) if race_like and classified is not None else timing
        if expected <= 0:
            continue
        shares = [min(1.0, timing / expected)]
        shares += [
            min(1.0, int(driver.get(key) or 0) / expected)
            for key in ("car_laps", "position_laps", "tyre_laps")
        ]
        lowest = min(lowest, *shares)
    return lowest


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


def _usable_laps(laps: pd.DataFrame, telemetry: Any, channels: tuple[str, ...], valid: Any) -> int:
    if telemetry is None or len(laps) == 0 or len(telemetry) == 0:
        return 0
    if any(channel not in telemetry.columns for channel in channels) or "SessionTime" not in telemetry.columns:
        return 0
    mask = valid(telemetry)
    times = _seconds(telemetry["SessionTime"])[mask]
    times = np.sort(times[np.isfinite(times)])
    starts = _seconds(laps["LapStartTime"])
    ends = _seconds(laps["Time"])
    return sum(1 for start, end in zip(starts, ends) if lap_is_usable(times, start, end))


def _car_valid(telemetry: pd.DataFrame) -> np.ndarray:
    return telemetry[list(CAR_CHANNELS)].notna().all(axis=1).to_numpy()


def _position_valid(telemetry: pd.DataFrame) -> np.ndarray:
    # F1 sends (0, 0) while it has no position for a car, such as before it
    # leaves the garage. Those samples are not positions.
    present = telemetry[list(POSITION_CHANNELS)].notna().all(axis=1)
    located = (telemetry["X"] != 0) | (telemetry["Y"] != 0)
    return (present & located).to_numpy()


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
    if len(laps) == 0 or not {"Compound", "TyreLife", "Stint"} <= set(laps.columns):
        return 0
    compound = laps["Compound"].astype("string").str.strip().str.upper()
    known = compound.notna() & ~compound.isin(_UNKNOWN_COMPOUNDS) & laps["Stint"].notna()
    if with_age:
        known = known & laps["TyreLife"].notna()
    return int(known.sum())


def _driver_codes(results: pd.DataFrame, laps: pd.DataFrame) -> dict[str, str]:
    """Driver number to three-letter code, for every driver in the result or the timing."""
    codes: dict[str, str] = {}
    if len(results) and "Abbreviation" in results.columns:
        for number, code in zip(_numbers(results), results["Abbreviation"]):
            codes[number] = str(code) if _present(code) else number
    if len(laps) and {"DriverNumber", "Driver"} <= set(laps.columns):
        for number, code in zip(laps["DriverNumber"].astype(str), laps["Driver"]):
            codes.setdefault(number, str(code) if _present(code) else number)
    return codes


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
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip() != ""


def _int_or_none(value: Any) -> int | None:
    if not _present(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
