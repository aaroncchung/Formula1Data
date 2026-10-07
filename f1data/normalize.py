"""A loaded FastF1 session as the rows that are published.

This replaces ``backend/app/ingestion/normalizer.py``, which turned a session
into dictionaries of whatever FastF1 held: times as pandas strings
(``0 days 01:22:52.191000``), lap times cut to the millisecond instead of
rounded, ``NaN`` passed through ``str``, and a ``session_id`` built from the
round number on every row (docs/architecture-review-findings.md, AR-05, AR-08,
AR-20). Here each row is a model from ``f1data/models.py``, so the shape and
the units are checked as the row is made.

Nothing in this module reads the calendar. What a session is comes from F1's
own session information, and its result from the classification the build was
given, or from the timing when there is none.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from f1data.analyses import POSITION_UNITS_PER_METRE
from f1data.classification import Classification
from f1data.coverage import RACE_LIKE_SESSION_TYPES, evaluate_coverage
from f1data.extras import (
    CIRCUIT_INFO,
    PIT_STOP_SERIES,
    WEATHER_SERIES,
    parse_pit_stop_series,
    weather_readings_sent,
)
from f1data.identity import SessionIdentity
from f1data.loaded import MISSING_AS_TEXT, present, result_numbers, text
from f1data.loaded import driver_codes as codes_by_number
from f1data.models import (
    Corner,
    Corners,
    Coverage,
    CoverageFeeds,
    DistanceSource,
    Driver,
    DriverCoverage,
    Lap,
    PitStop,
    PitStopSources,
    RaceControlMessage,
    ReferenceLap,
    Result,
    SessionSummary,
    Shortfall,
    Stint,
    Team,
    WeatherSample,
)
from f1data.telemetry import LapSamples, SessionTelemetry

_NS_PER_MS = 1_000_000
_METRES_PER_SECOND_IN_KPH = 3.6
# A circuit's archived corner positions are taken to be of the track a session
# drove when they lie on it: on the line of the reference lap, measured to its
# nearest sample. In the 18 races and sprints of 2026 archived with corner
# positions every corner is within 20 m of that, at a median of 1 to 3 m. No
# session has failed this yet. It is here for a map of another layout, and for
# a session with no lap whose position data is whole.
CORNERS_FIT_WITHIN_MEDIAN_M = 10.0
CORNERS_FIT_WITHIN_M = 50.0
# The reference lap is one whose position samples are never further apart than
# this. In four of five sessions measured they never are: the largest step of
# a clean lap is 60 m at the median lap and 124 m at the worst. In the 2026
# Hungarian race F1's position feed repeats itself for most of every lap after
# the first few, so that 1,168 of 1,279 clean laps have a step of over 150 m,
# and the fastest lap one of 347 m. Measured against that lap the corners
# looked 44 m off the track at the median and up to 116 m, and FastF1, which
# places corners along the fastest lap, put two pairs of them at one point of
# it. They are within a metre of the line of the laps whose position data is
# whole, and within 14 m of the nearest sample of the fastest of those.
REFERENCE_LAP_MAX_STEP_M = 150.0
_HEX_COLOUR = re.compile(r"^#?([0-9A-Fa-f]{6})$")
# A classification has to have these for every driver before it is published.
_REQUIRED_OF_A_RESULT = ("positionText", "status", "points", "grid", "laps")

_logger = logging.getLogger(__name__)


# F1's track status while a session is stopped.
_RED_FLAG_STATUS = "5"

# How long after a car has left the pit lane a report of its stop that names
# no lap is still taken to be of that stop. F1 reports a stop as the car
# leaves; the late ones of the 2026 Australian GP came up to 66 seconds after.
_LATE_REPORT_MS = 120_000
# How far F1's own pit-lane time may be from the timing's for the two to be
# of one stop. For the twenty-eight stops of that race they are within 0.4 s.
_SAME_STOP_MS = 2_000

# F1's weather service sends 0.0 for a sensor that gave it no reading. The
# track temperature of the 2026 Azerbaijan GP reads 46.6, 0.0, 47.3 in three
# samples a minute apart, and again later in the race; the Bahrain GP's does
# the same twice. Nothing in the line says so. A temperature or a humidity of
# exactly zero is taken for that when the readings either side of it are both
# at least this far from zero, and for a reading in every other case.
_DROPOUT_JUMP = 20.0
_SENSORS_THAT_DROP_OUT = ("air_temp_c", "track_temp_c", "humidity_pct")


class SessionDataError(RuntimeError):
    """The session cannot be published as it stands: its laps or its result are unusable."""


# --- the session ---------------------------------------------------------------


def summary(
    identity: SessionIdentity,
    session: Any,
    drivers: list[Driver],
    laps: list[Lap],
    weather: list[WeatherSample],
) -> SessionSummary:
    return SessionSummary(
        session_key=identity.session_key,
        year=identity.year,
        meeting=identity.meeting_name,
        session=identity.session_name,
        session_type=identity.session_type,
        circuit=identity.circuit_name,
        country=identity.country,
        driver_count=len(drivers),
        lap_count=len(laps),
        weather_summary=_weather_summary(weather),
        clock_zero_utc=_clock_zero_utc(session),
        is_sample=False,
    )


def driver_codes(session: Any) -> dict[str, str]:
    """Driver number to the code that names the driver in every artifact.

    A driver is found by number everywhere, and named by this: the timing's
    code, or the result's, or the car number as text for a driver neither
    names (f1data/loaded.py).
    """
    return codes_by_number(_frame(session, "results"), _frame(session, "laps"))


def drivers(session: Any, codes: dict[str, str]) -> list[Driver]:
    """Everyone in F1's driver list, the result or the timing, in the order FastF1 holds them."""
    results = _frame(session, "results")
    rows: list[Driver] = []
    seen: set[str] = set()
    for number, (_, row) in zip(_driver_numbers(results), results.iterrows()):
        code = codes.get(number) or _text(row.get("Abbreviation"))
        if not code or code in seen:
            continue
        seen.add(code)
        team_name = _text(row.get("TeamName"))
        rows.append(
            Driver(
                driver_id=code.lower(),
                code=code,
                full_name=_full_name(row) or code,
                number=_int(number),
                team=Team(team_id=_slug(team_name), name=team_name, color=_colour(row.get("TeamColor")))
                if team_name
                else None,
                country=_text(row.get("CountryCode")),
            )
        )
    # With no driver list and no classification the timing still says which
    # cars ran. They are the session's drivers, by number and nothing more.
    for number, code in codes.items():
        if code not in seen:
            seen.add(code)
            rows.append(
                Driver(
                    driver_id=code.lower(), code=code, full_name=code, number=_int(number), team=None, country=None
                )
            )
    return rows


def _full_name(row: Any) -> str | None:
    """A driver's name from its two parts, since FastF1 joins them whether or not they are there.

    With no first name its ``FullName`` reads ``None Verstappen``.
    """
    parts = [part for part in (_text(row.get("FirstName")), _text(row.get("LastName"))) if part]
    if parts:
        return " ".join(parts)
    joined = _text(row.get("FullName"))
    if joined and not all(word in MISSING_AS_TEXT for word in joined.split()):
        return joined
    return None


def laps(session: Any, codes: dict[str, str] | None = None) -> list[Lap]:
    frame = _frame(session, "laps")
    if len(frame) == 0:
        raise SessionDataError(
            "The session has no laps. FastF1 makes none when the timing, the tyre data, the track status "
            "or the session status is missing from the snapshot"
        )
    codes = driver_codes(session) if codes is None else codes
    rows: list[Lap] = []
    for _, row in frame.iterrows():
        # By car number: the code written on a lap is empty when F1's driver
        # list did not arrive, and the lap is still that car's.
        code = codes.get(_text(row.get("DriverNumber")) or "") or _text(row.get("Driver"))
        number = _int(row.get("LapNumber"))
        if not code or number is None or number <= 0:
            continue
        accurate = _bool(row.get("IsAccurate"))
        rows.append(
            Lap(
                driver_code=code.upper(),
                lap_number=number,
                lap_time_ms=_milliseconds(row.get("LapTime")),
                sector_1_ms=_milliseconds(row.get("Sector1Time")),
                sector_2_ms=_milliseconds(row.get("Sector2Time")),
                sector_3_ms=_milliseconds(row.get("Sector3Time")),
                compound=row.get("Compound"),
                tyre_age=_int(row.get("TyreLife")),
                stint=_int(row.get("Stint")),
                position=_int(row.get("Position")),
                is_pit_in_lap=_present(row.get("PitInTime")),
                is_pit_out_lap=_present(row.get("PitOutTime")),
                is_deleted=bool(_bool(row.get("Deleted"))),
                is_accurate=True if accurate is None else accurate,
                track_status=_text(row.get("TrackStatus")),
            )
        )
    if not rows:
        raise SessionDataError("The session's timing names no driver and lap")
    return rows


def stints(lap_rows: list[Lap]) -> list[Stint]:
    """Each run of laps on one set of tyres, driver by driver in the order the timing shows them.

    A run is consecutive laps: no two runs of a driver share a lap. F1 numbers
    the sets a driver uses, and a new number starts a new run. So does a
    compound that changes to another under one number, which is F1 correcting
    itself. A lap with no compound does not: under the same number it is the
    same set of tyres, and F1 often names a set's compound only some laps
    after it went on. The run then has the compound F1 did name. A run none of
    whose laps has one has none.
    """
    by_driver: dict[str, list[Lap]] = {}
    for lap in lap_rows:
        by_driver.setdefault(lap.driver_code, []).append(lap)
    runs: list[Stint] = []
    for driver, driver_laps in by_driver.items():
        current: dict[str, Any] | None = None
        for lap in sorted(driver_laps, key=lambda row: row.lap_number):
            compound = lap.compound.value if lap.compound is not None else None
            same_set = (
                current is not None
                and current["stint"] == lap.stint
                and (compound is None or current["compound"] is None or current["compound"] == compound)
            )
            if not same_set:
                current = {"stint": lap.stint, "compound": compound, "laps": []}
                runs.append(current)  # type: ignore[arg-type]
            assert current is not None
            current["compound"] = current["compound"] or compound
            current["laps"].append(lap.lap_number)
            current["driver"] = driver
    return [
        Stint(
            driver_code=run["driver"],  # type: ignore[index]
            stint=run["stint"],  # type: ignore[index]
            compound=run["compound"],  # type: ignore[index]
            start_lap=run["laps"][0],  # type: ignore[index]
            end_lap=run["laps"][-1],  # type: ignore[index]
            lap_count=len(run["laps"]),  # type: ignore[index]
        )
        for run in runs
    ]


# --- the result ----------------------------------------------------------------


def results(classification: Classification | None, session: Any, codes: dict[str, str]) -> list[Result]:
    """The classification, or the order on track when Jolpica has none.

    With a classification, every figure is Jolpica's and nothing else. A
    driver with laps in the timing whom it leaves out comes after the
    classified, with no position and no figures at all, whatever the archive
    recorded for them.
    """
    if classification is None:
        return _provisional_results(session, codes)
    rows = sorted(
        classification.rows,
        key=lambda row: (_int(row.get("position")) is None, _int(row.get("position")) or 0),
    )
    positions = [_int(row.get("position")) for row in rows]
    if len(rows) < 2 or positions != list(range(1, len(rows) + 1)):
        raise SessionDataError(
            f"The classification must hold unique positions 1 to {len(rows)}, and holds {positions}"
        )
    built: list[Result] = []
    for row in rows:
        number = str(row.get("number")) if row.get("number") is not None else ""
        code = codes.get(number) or _text(row.get("driverCode"))
        missing = [field for field in _REQUIRED_OF_A_RESULT if not _present(row.get(field))]
        if not code or missing:
            raise SessionDataError(
                f"The classification is missing {', '.join(missing) or 'a driver code'} for "
                f"{code or f'driver number {number}'}"
            )
        position = int(row["position"])
        laps_completed = _int(row.get("laps"))
        # Jolpica gives the winner a race time and everyone else the time
        # they took the flag behind, whichever lap they were on.
        race_time = _int(row.get("totalRaceTime"))
        winner_laps = _int(rows[0].get("laps"))
        # Classified is not the same as finished: a driver who retires
        # having covered nine tenths of the distance has a place, and did not
        # take the flag a number of laps down.
        classified = (_text(row.get("positionText")) or "").isdigit() and _took_the_flag(row.get("status"))
        down = (
            winner_laps - laps_completed
            if classified
            and winner_laps is not None
            and laps_completed is not None
            and laps_completed < winner_laps
            else None
        )
        built.append(
            Result(
                position=position,
                driver_code=code.upper(),
                classified_position=_text(row.get("positionText")),
                status=_text(row.get("status")),
                points=float(row["points"]),
                grid=_int(row.get("grid")),
                time_ms=race_time if position == 1 else None,
                gap_ms=race_time if position != 1 and laps_completed == winner_laps else None,
                laps_down=down,
                behind_at_flag_ms=race_time if down else None,
                laps=laps_completed,
                provisional=False,
            )
        )
    if len({row.driver_code for row in built}) != len(built):
        raise SessionDataError("The classification names a driver twice")
    listed = {row.driver_code for row in built}
    for code in sorted(_codes_with_laps(session, codes) - listed):
        built.append(
            Result(
                position=None,
                driver_code=code,
                classified_position=None,
                status=None,
                points=None,
                grid=None,
                time_ms=None,
                gap_ms=None,
                laps_down=None,
                behind_at_flag_ms=None,
                laps=None,
                provisional=False,
            )
        )
    return built


def _took_the_flag(status: Any) -> bool:
    """Whether a result's status is that of a driver who was running at the end.

    Jolpica says "Finished" or "Lapped"; the service it replaced said
    "+1 Lap", "+2 Laps". Anything else is a reason the driver stopped.
    """
    text = (_text(status) or "").strip().lower()
    return text in {"finished", "lapped"} or (text.startswith("+") and "lap" in text)


def _codes_with_laps(session: Any, codes: dict[str, str]) -> set[str]:
    """The drivers F1 timed at least one lap for."""
    frame = _frame(session, "laps")
    if len(frame) == 0 or "DriverNumber" not in frame.columns:
        return set()
    timed = frame
    if "FastF1Generated" in frame.columns:
        timed = frame[~frame["FastF1Generated"].fillna(False).astype(bool)]
    numbers = {_text(number) for number in timed["DriverNumber"]}
    return {codes[number] for number in numbers if number in codes}


def _provisional_results(session: Any, codes: dict[str, str]) -> list[Result]:
    """The order on track from the timing alone, for a session with no classification.

    Most laps first, then whoever finished their last lap sooner. A driver who
    took the flag after the leader has the time they took it behind, as a gap
    on the leader's lap and beside the laps they were down otherwise; one who
    stopped before then has neither. Nothing here is official. For the 2026
    Austrian GP it is the classification, all 22 places, to the millisecond.
    """
    frame = _frame(session, "laps")
    last: dict[str, tuple[int, int]] = {}
    if len(frame) and {"DriverNumber", "LapNumber", "Time"} <= set(frame.columns):
        generated = (
            frame["FastF1Generated"].fillna(False).astype(bool)
            if "FastF1Generated" in frame.columns
            else pd.Series(False, index=frame.index)
        )
        for number, lap, end in zip(
            frame["DriverNumber"].astype(str)[~generated],
            frame["LapNumber"][~generated],
            frame["Time"][~generated],
        ):
            lap_number, finished = _int(lap), _milliseconds(end)
            if lap_number is None or finished is None:
                continue
            if number not in last or lap_number > last[number][0]:
                last[number] = (lap_number, finished)

    order = sorted(
        codes,
        key=lambda number: (
            -last.get(number, (0, 0))[0],
            last.get(number, (0, 0))[1],
            _int(number) or 0,
            number,
        ),
    )
    leader_laps, leader_finished = last[order[0]] if order and order[0] in last else (0, None)
    rows: list[Result] = []
    for position, number in enumerate(order, start=1):
        completed, finished = last.get(number, (0, None))
        behind = finished - leader_finished if finished is not None and leader_finished is not None else None
        took_the_flag = position > 1 and behind is not None and behind >= 0
        down = leader_laps - completed if took_the_flag and completed < leader_laps else None
        rows.append(
            Result(
                position=position,
                driver_code=codes[number],
                classified_position=None,
                status=None,
                points=None,
                grid=None,
                time_ms=None,
                gap_ms=behind if took_the_flag and not down else None,
                laps_down=down,
                behind_at_flag_ms=behind if down else None,
                laps=completed,
                provisional=True,
            )
        )
    return rows


# --- pit stops -----------------------------------------------------------------


def pit_stops(session: Any, extras: dict[str, bytes], codes: dict[str, str]) -> list[PitStop]:
    """Every entry to the pit lane the timing shows, with F1's own figures beside it.

    The timing gives the pit-lane transit time: the gap between the pit-entry
    time on one lap and the pit-exit time on the next. F1's pit-stop feed
    gives the time the car stood still and its own pit-lane time, for the
    stops it covers, which is not all of them (AR-16). The two are matched by
    driver and lap. A report with no lap, which F1 sometimes sends late, is
    matched by when it was made and how long it says the car was in the pit
    lane, and is left out when that does not single out one stop. A stop only
    the feed reports is kept, after the timing's.
    """
    # What the timing shows: for each driver, by lap, when the car came in and
    # how long it was before it came out.
    timed: dict[str, dict[int, tuple[int, int | None]]] = {}
    frame = _frame(session, "laps")
    if len(frame) and {"DriverNumber", "LapNumber", "PitInTime", "PitOutTime"} <= set(frame.columns):
        by_driver: dict[str, dict[int, tuple[Any, Any]]] = {}
        for car, lap, came_in, went_out in zip(
            frame["DriverNumber"], frame["LapNumber"], frame["PitInTime"], frame["PitOutTime"]
        ):
            code = codes.get(_text(car) or "")
            number = _int(lap)
            if code and number is not None:
                by_driver.setdefault(code, {})[number] = (came_in, went_out)
        for code, driver_laps in by_driver.items():
            for number in sorted(driver_laps):
                came_in = _milliseconds(driver_laps[number][0])
                if came_in is None:
                    continue
                went_out = _milliseconds(driver_laps.get(number + 1, (None, None))[1])
                duration = went_out - came_in if went_out is not None and went_out >= came_in else None
                timed.setdefault(code, {})[number] = (came_in, duration)

    clock_zero = _clock_zero(session)
    reported: dict[tuple[str, int], dict[str, Any]] = {}
    without_a_lap: list[tuple[str, dict[str, Any]]] = []
    for stop in parse_pit_stop_series(extras.get(PIT_STOP_SERIES, b"")):
        code = codes.get(str(stop["driver_number"]))
        if code is None:
            _logger.warning(
                "The pit-stop feed names driver number %s, who is not in the session", stop["driver_number"]
            )
        elif stop["lap_number"] is None:
            without_a_lap.append((code, stop))
        else:
            # Two stops F1 gives one lap: the later is the one that stands.
            reported[(code, int(stop["lap_number"]))] = stop
    # After every stop that says its lap, so that none of those is taken for
    # the stop of a report that does not.
    for code, stop in without_a_lap:
        taken = {lap for driver, lap in reported if driver == code}
        lap_number = _lap_of_a_late_report(stop, timed.get(code, {}), clock_zero, taken)
        if lap_number is None:
            _logger.warning(
                "The pit-stop feed reports a stop of %s at %s with no lap, and the timing does not single "
                "out a stop it is of",
                code,
                stop.get("time_utc"),
            )
            continue
        reported[(code, lap_number)] = stop

    red_flags = _red_flag_periods(session)
    rows: list[PitStop] = []
    for code, stops in timed.items():
        for number, (came_in, duration) in stops.items():
            waited = any(
                start <= _left(came_in, duration) and (end is None or end >= came_in)
                for start, end in red_flags
            )
            rows.append(
                _pit_stop(code, number, came_in, duration, reported.pop((code, number), None), waited)
            )
    for (code, number), stop in sorted(reported.items()):
        rows.append(_pit_stop(code, number, None, None, stop, False))
    return rows


def _left(came_in: int, duration: int | None) -> int:
    """When a car left the pit lane, or when it came in if it never came out."""
    return came_in + duration if duration is not None else came_in


def _lap_of_a_late_report(
    stop: dict[str, Any],
    timed: dict[int, tuple[int, int | None]],
    clock_zero: int | None,
    taken: frozenset[int] | set[int] = frozenset(),
) -> int | None:
    """The lap of a stop F1 reported with no lap, or ``None`` when the timing does not single one out.

    F1 reports a stop as the car leaves the pit lane, and says which lap. In
    the 2026 Australian GP twenty of the twenty-eight reports came between
    one second and 66 seconds late and said no lap. Such a report is of a
    stop the timing shows the car finishing: one it came out of no more than
    two minutes before the report and not after it, that no other report
    names (``taken``), and whose time in the pit lane is the report's own
    where the report gives one. A car the timing does not show leaving was
    not finishing a stop. When two stops answer to all that, or none does,
    the report is of neither: a figure left out is better than a figure
    against the wrong lap.
    """
    if clock_zero is None or not stop.get("time_utc"):
        return None
    try:
        moment = pd.Timestamp(stop["time_utc"])
        if moment.tzinfo is not None:
            moment = moment.tz_convert("UTC").tz_localize(None)
        reported_at = _round_ms(moment.value - clock_zero)
    except (TypeError, ValueError, OverflowError):
        return None
    in_the_lane = stop.get("pit_lane_ms")
    could_be: list[int] = []
    for lap_number, (came_in, duration) in timed.items():
        if duration is None or lap_number in taken:
            continue
        left = came_in + duration
        # A second's grace: the feed's clock and the timing's are rounded apart.
        if not left - 1000 <= reported_at <= left + _LATE_REPORT_MS:
            continue
        if in_the_lane is not None and abs(in_the_lane - duration) > _SAME_STOP_MS:
            continue
        could_be.append(lap_number)
    return could_be[0] if len(could_be) == 1 else None


def _red_flag_periods(session: Any) -> list[tuple[int, int | None]]:
    """When the session was red-flagged: start and end in milliseconds on the session clock.

    From the track status, where a red flag is status 5 until the next status.
    The end is ``None`` for one still out when the feed stops.
    """
    frame = _frame(session, "track_status")
    if len(frame) == 0 or not {"Time", "Status"} <= set(frame.columns):
        return []
    changes = sorted(
        (moment, _text(status) or "")
        for moment, status in ((_milliseconds(time), status) for time, status in zip(frame["Time"], frame["Status"]))
        if moment is not None
    )
    return [
        (moment, changes[index + 1][0] if index + 1 < len(changes) else None)
        for index, (moment, status) in enumerate(changes)
        if status == _RED_FLAG_STATUS
    ]


def _pit_stop(
    code: str,
    lap_number: int,
    came_in: int | None,
    duration: int | None,
    reported: dict[str, Any] | None,
    under_red_flag: bool,
) -> PitStop:
    stationary = reported.get("stationary_ms") if reported else None
    pit_lane = reported.get("pit_lane_ms") if reported else None
    return PitStop(
        driver_code=code,
        lap_number=lap_number,
        entry_time_ms=came_in,
        duration_ms=duration,
        under_red_flag=under_red_flag,
        stationary_ms=stationary,
        pit_lane_ms=pit_lane,
        sources=PitStopSources(
            duration_ms="timing" if duration is not None else None,
            stationary_ms="pit_stop_series" if stationary is not None else None,
            pit_lane_ms="pit_stop_series" if pit_lane is not None else None,
        ),
    )


# --- weather and race control --------------------------------------------------


def weather(session: Any, session_type: str, extras: dict[str, bytes] | None = None) -> list[WeatherSample]:
    """Every weather sample, with a reading only where F1 sent one.

    The values are FastF1's. Which of them F1 sent is asked of the feed
    itself, archived beside the session (f1data/extras.py): FastF1 writes 0
    and "no rain" for a reading a line leaves out. A snapshot taken before
    the feed was kept has no bytes to ask, and its samples are published as
    FastF1 has them; the 51 sessions archived by then were checked, and
    every line of every one gives every reading.

    One thing is not F1's as sent: a zero F1 sends for a sensor that had no
    reading (``_without_dropouts``).
    """
    frame = _frame(session, "weather_data")
    if len(frame) == 0 or "Time" not in frame.columns:
        return []
    leader_lap = _leader_lap(session) if session_type.upper() in RACE_LIKE_SESSION_TYPES else None
    sent = weather_readings_sent(extras[WEATHER_SERIES]) if extras and WEATHER_SERIES in extras else None
    seen_at: dict[int, int] = {}
    rows: list[WeatherSample] = []
    for _, row in frame.iterrows():
        moment = _milliseconds(row.get("Time"))
        if moment is None:
            continue
        given = None
        if sent is not None:
            # The nth sample with a time is the nth line with it.
            lines = sent.get(moment, [])
            given = lines[seen_at.get(moment, 0)] if seen_at.get(moment, 0) < len(lines) else frozenset()
            seen_at[moment] = seen_at.get(moment, 0) + 1

        def reading(name: str) -> Any:
            return row.get(name) if given is None or name in given else None

        wind = _float(reading("WindSpeed"))
        rain = _bool(reading("Rainfall"))
        rows.append(
            WeatherSample(
                time_ms=moment,
                lap_number=leader_lap(moment) if leader_lap is not None else None,
                air_temp_c=_float(reading("AirTemp")),
                track_temp_c=_float(reading("TrackTemp")),
                humidity_pct=_float(reading("Humidity")),
                # FastF1's table has no missing rain, only "no rain".
                rainfall=bool(rain) if given is None else rain,
                wind_speed_kph=wind * _METRES_PER_SECOND_IN_KPH if wind is not None else None,
            )
        )
    return _without_dropouts(rows)


def _without_dropouts(rows: list[WeatherSample]) -> list[WeatherSample]:
    """The samples with no reading where F1 sent the zero it sends in place of one."""
    for name in _SENSORS_THAT_DROP_OUT:
        values = [getattr(row, name) for row in rows]
        for index, value in enumerate(values):
            if value is None or value != 0:
                continue
            either_side = [
                next((other for other in reversed(values[:index]) if other), None),
                next((other for other in values[index + 1 :] if other), None),
            ]
            near = [other for other in either_side if other is not None]
            if near and all(abs(other) >= _DROPOUT_JUMP for other in near):
                rows[index] = rows[index].model_copy(update={name: None})
    return rows


def _leader_lap(session: Any) -> Any:
    """A function from a time on the session clock to the lap the leader was on then."""
    frame = _frame(session, "laps")
    if len(frame) == 0 or not {"LapNumber", "LapStartTime", "Time"} <= set(frame.columns):
        return lambda moment: None
    timed = frame
    if "FastF1Generated" in frame.columns:
        timed = frame[~frame["FastF1Generated"].fillna(False).astype(bool)]
    known = timed[timed["LapStartTime"].notna() & timed["LapNumber"].notna()]
    if len(known) == 0:
        return lambda moment: None
    order = np.argsort(known["LapStartTime"].to_numpy(dtype="timedelta64[ns]").astype("int64"), kind="stable")
    starts = known["LapStartTime"].to_numpy(dtype="timedelta64[ns]").astype("int64")[order] // _NS_PER_MS
    furthest = np.maximum.accumulate(known["LapNumber"].to_numpy(dtype=float)[order]).astype(int)
    ends = timed["Time"].dropna()
    flag = int(ends.max().value // _NS_PER_MS) if len(ends) else int(starts[-1])

    def lap_at(moment: int) -> int | None:
        if moment < starts[0] or moment > flag:
            return None
        return int(furthest[int(np.searchsorted(starts, moment, side="right")) - 1])

    return lap_at


def race_control(session: Any) -> list[RaceControlMessage]:
    frame = _frame(session, "race_control_messages")
    if len(frame) == 0:
        return []
    clock_zero = _clock_zero(session)
    rows: list[RaceControlMessage] = []
    for _, row in frame.iterrows():
        moment = row.get("Time")
        on_clock = None
        if _present(moment) and clock_zero is not None:
            on_clock = _round_ms(pd.Timestamp(moment).value - clock_zero)
        rows.append(
            RaceControlMessage(
                time_ms=on_clock,
                lap_number=_int(row.get("Lap")),
                category=_text(row.get("Category")) or "Other",
                message=_text(row.get("Message")) or "",
                flag=_text(row.get("Flag")),
                scope=_text(row.get("Scope")),
            )
        )
    return rows


# --- the circuit ---------------------------------------------------------------


def circuit_corners(extras: dict[str, bytes], telemetry: SessionTelemetry, lap_rows: list[Lap]) -> Corners:
    """The circuit's corners from the archive, placed along the lap if they are not already.

    The corner positions come from MultiViewer when the session is fetched.
    FastF1 places each along the lap using the fastest lap's position data,
    and when that fails the corners are archived without distances
    (f1data/extras.py). The build then places them itself, on the fastest
    clean lap of the session whose position data is whole. It does the same
    when the archived distances do not go round the lap in the order of the
    corners: they were measured on a lap that did not show the corners.

    The same lap says whether the corners lie on the track at all, and the
    artifact says so.
    """
    try:
        archived = json.loads(extras.get(CIRCUIT_INFO, b"{}").decode("utf-8", errors="replace"))
    except ValueError:
        archived = {}
    if not isinstance(archived, dict):
        archived = {}
    found = []
    for corner in archived.get("corners") or []:
        if not isinstance(corner, dict):
            continue
        number, x, y = _int(corner.get("number")), _float(corner.get("x")), _float(corner.get("y"))
        if number is None or x is None or y is None:
            continue
        found.append(
            {
                "number": number,
                "letter": _text(corner.get("letter")),
                "x": x,
                "y": y,
                "angle": _float(corner.get("angle")),
                "distance_m": _float(corner.get("distance_m")),
            }
        )

    source: DistanceSource | None = None
    reference: ReferenceLap | None = None
    furthest: float | None = None
    fits: bool | None = None
    lap = _reference_lap(telemetry, lap_rows) if found else None
    if lap is not None:
        reference = ReferenceLap(
            driver_code=lap.driver_code,
            lap_number=lap.lap_number,
            length_m=float(lap.distance_m[-1] - lap.distance_m[0]),
        )
        squared = [(lap.x - corner["x"]) ** 2 + (lap.y - corner["y"]) ** 2 for corner in found]
        off_track = [float(np.sqrt(np.nanmin(each))) / POSITION_UNITS_PER_METRE for each in squared]
        furthest = max(off_track)
        fits = float(np.median(off_track)) <= CORNERS_FIT_WITHIN_MEDIAN_M and furthest <= CORNERS_FIT_WITHIN_M
    archived_distances = [corner["distance_m"] for corner in found]
    if found and _goes_round_the_lap(archived_distances):
        source = DistanceSource.ARCHIVE
    elif lap is not None:
        source = DistanceSource.TELEMETRY
        for corner, each in zip(found, squared):
            corner["distance_m"] = float(lap.distance_m[int(np.nanargmin(each))])
    else:
        found = [{**corner, "distance_m": None} for corner in found]
    return Corners(
        rotation=_float(archived.get("rotation")),
        corners=[Corner(**corner) for corner in found],
        distance_source=source,
        reference_lap=reference,
        off_track_m=furthest,
        fits_track=fits,
    )


def _goes_round_the_lap(distances: list[float | None]) -> bool:
    """True when every corner has a distance and each is further round than the one before."""
    if any(distance is None for distance in distances):
        return False
    return all(one < other for one, other in zip(distances, distances[1:]))


def _reference_lap(telemetry: SessionTelemetry, lap_rows: list[Lap]) -> LapSamples | None:
    """The fastest accurate, undeleted lap whose position data is whole.

    Failing that, the fastest that has position data at all: the corners are
    then measured against what there is, and may not appear to fit.
    """
    candidates = sorted(
        (lap.lap_time_ms, lap.driver_code, lap.lap_number)
        for lap in lap_rows
        if lap.lap_time_ms is not None
        and lap.is_accurate
        and not lap.is_deleted
        and not lap.is_pit_in_lap
        and not lap.is_pit_out_lap
    )
    placed = [
        samples
        for _, driver, number in candidates
        if (samples := telemetry.laps.get((driver, number))) is not None and samples.has_position
    ]
    for samples in placed:
        steps = np.hypot(np.diff(samples.x), np.diff(samples.y)) / POSITION_UNITS_PER_METRE
        # A sample with no position has no step to it or from it, and is not held against the lap.
        if not (steps > REFERENCE_LAP_MAX_STEP_M).any():
            return samples
    return placed[0] if placed else None


# --- coverage ------------------------------------------------------------------


def coverage(measurement: dict[str, Any], codes: dict[str, str] | None = None) -> Coverage:
    """A measurement from ``f1data/coverage.py`` and what it is short of, as it is published.

    The measurement is the snapshot's record, which may have been written
    before a figure here was counted, or by something else. The bars are
    judged by ``evaluate_coverage``, which the archive has already had read
    it (``f1data/archive.py``); a figure only this reads is published as
    nothing when it is not a number, and never stops a build.

    A record names each driver as the fetch could: by car number when F1's
    driver list had not arrived. ``codes`` are the build's, by number, and a
    driver is published under the code the rest of the generation uses.
    """
    shortfalls = evaluate_coverage(measurement)
    feeds = measurement.get("feeds", {})
    measured = measurement.get("drivers", {})
    named = {
        key: (codes or {}).get(str(driver.get("number")), key) if isinstance(driver, dict) else key
        for key, driver in measured.items()
    }
    return Coverage(
        complete=not shortfalls,
        shortfalls=[
            Shortfall(bar=item.bar, driver=named.get(item.driver, item.driver), detail=item.detail)
            for item in shortfalls
        ],
        feeds=CoverageFeeds(**{name: bool(feeds.get(name)) for name in CoverageFeeds.model_fields}),
        session_ended=bool(measurement.get("session_ended")),
        total_laps=_int(measurement.get("total_laps")),
        pit_stops_in_timing=_int(measurement.get("pit_stops_in_timing")) or 0,
        pit_stops_in_series=_int(measurement.get("pit_stops_in_series")) or 0,
        circuit_corners=_int(measurement.get("circuit_corners")) or 0,
        max_sample_gap_seconds=_float(measurement.get("max_sample_gap_seconds")) or 0.0,
        drivers=[
            DriverCoverage(
                driver_code=named[code],
                number=str(driver.get("number")),
                in_driver_list=bool(driver.get("in_driver_list")),
                classified_laps=_int(driver.get("classified_laps")),
                timing_laps=_int(driver.get("timing_laps")) or 0,
                generated_laps=_int(driver.get("generated_laps")) or 0,
                car_laps=_int(driver.get("car_laps")) or 0,
                position_laps=_int(driver.get("position_laps")) or 0,
                tyre_laps=_int(driver.get("tyre_laps")) or 0,
                tyre_age_laps=_int(driver.get("tyre_age_laps")) or 0,
            )
            for code, driver in sorted(measured.items(), key=lambda item: named[item[0]])
        ],
    )


# --- values --------------------------------------------------------------------


def _weather_summary(samples: Iterable[WeatherSample]) -> str:
    samples = list(samples)
    if not samples:
        return "Weather data unavailable"
    parts = []
    for label, values in (
        ("air", [sample.air_temp_c for sample in samples if sample.air_temp_c is not None]),
        ("track", [sample.track_temp_c for sample in samples if sample.track_temp_c is not None]),
    ):
        if values:
            parts.append(f"{label} {min(values):.1f}-{max(values):.1f}C")
    rain = [sample.rainfall for sample in samples if sample.rainfall is not None]
    if rain:
        parts.append("rain" if any(rain) else "dry")
    return ", ".join(parts) or "Weather data unavailable"


def _clock_zero(session: Any) -> int | None:
    try:
        moment = pd.Timestamp(session.t0_date)
    except Exception:
        return None
    return None if pd.isna(moment) else int(moment.value)


def _clock_zero_utc(session: Any) -> str | None:
    clock_zero = _clock_zero(session)
    if clock_zero is None:
        return None
    # FastF1 holds the session's dates as naive UTC.
    moment = pd.Timestamp(_round_ms(clock_zero) * _NS_PER_MS)
    return f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}.{moment.microsecond // 1000:03d}Z"


def _round_ms(nanoseconds: int) -> int:
    """Whole milliseconds, halves rounded up. The old normaliser cut them off."""
    return (int(nanoseconds) + _NS_PER_MS // 2) // _NS_PER_MS


def _milliseconds(value: Any) -> int | None:
    """A pandas duration in whole milliseconds, or ``None`` for a missing one."""
    if not _present(value):
        return None
    try:
        return _round_ms(pd.Timedelta(value).value)
    except (TypeError, ValueError):
        return None


# Not ``None``, not NaN, and not the word a cast to text made of either;
# and a string with something in it, or ``None`` (f1data/loaded.py).
_present = present
_text = text


def _int(value: Any) -> int | None:
    if not _present(value) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(round(number)) if np.isfinite(number) else None


def _float(value: Any) -> float | None:
    if not _present(value) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _bool(value: Any) -> bool | None:
    if not _present(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        text = str(value).strip().lower()
        if text in {"true", "yes", "on"}:
            return True
        if text in {"false", "no", "off"}:
            return False
    return None


def _colour(value: Any) -> str | None:
    match = _HEX_COLOUR.match(_text(value) or "")
    return f"#{match.group(1).upper()}" if match else None


def _slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-")


def _driver_numbers(results: pd.DataFrame) -> list[str]:
    return [number or "" for number in result_numbers(results)]


def _frame(session: Any, attribute: str) -> pd.DataFrame:
    # FastF1 raises DataNotLoadedError for anything a missing feed left unset.
    try:
        value = getattr(session, attribute)
    except Exception:
        return pd.DataFrame()
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()
