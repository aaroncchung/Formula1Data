"""Data a build needs that FastF1 does not load with a session.

A build may not fetch from a host that might refuse it, so anything of this
kind is fetched and archived with the session
(docs/architecture-review-findings.md, section 6, rule 4):

* ``PitStopSeries``, the F1 feed with each stop's stationary time and
  pit-lane time. FastF1 does not parse it (AR-16).
* The circuit's corner positions, which FastF1 takes from MultiViewer (AR-17).
* ``WeatherData``, as F1 sent it. FastF1 does load this one, and where a line
  leaves a sensor out it writes a zero, which its table cannot afterwards tell
  from a zero that was sent. The bytes are kept to say which is which.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

PIT_STOP_SERIES = "PitStopSeries.jsonStream"
WEATHER_SERIES = "WeatherData.jsonStream"
CIRCUIT_INFO = "circuit-info.json"

# The readings of a weather line that are numbers, by F1's names for them.
_WEATHER_NUMBERS = ("AirTemp", "Humidity", "Pressure", "TrackTemp", "WindDirection", "WindSpeed")
_STREAM_CLOCK = re.compile(r"^(\d+):(\d{2}):(\d{2})\.(\d{3})$")

# Each line of an F1 stream starts with the session time, as HH:MM:SS.mmm.
_STREAM_TIMESTAMP_CHARS = 12
# No stop and no drive down the pit lane lasts longer than the day it is in.
_LONGEST_DURATION_SECONDS = 24 * 60 * 60.0

_logger = logging.getLogger(__name__)


def fetch_extras(fastf1: Any, session: Any, archive_path: str) -> dict[str, bytes]:
    """Fetch what is there, by name. A missing entry means it did not arrive.

    Called inside the fetch's cache and request log, so both requests are
    rate-limited and recorded like FastF1's own.
    """
    from fastf1 import _api

    extras: dict[str, bytes] = {}
    # The weather is asked for a second time: FastF1 has just loaded it, so
    # the answer comes out of its cache of responses.
    for name in (PIT_STOP_SERIES, WEATHER_SERIES):
        try:
            response = fastf1.Cache.requests_get(
                f"{_api.base_url}/static/{archive_path}{name}", headers=_api.headers
            )
            # F1 answers 403 for a feed it does not hold, as it did for the
            # pit stops of races before late 2024.
            if response.status_code == 200 and response.content:
                extras[name] = response.content
        except Exception as exc:
            _logger.warning("Could not fetch %s: %s", name, exc)

    try:
        info = _circuit_info(fastf1, session)
        if info is not None:
            extras[CIRCUIT_INFO] = _dump(circuit_info_json(info))
    except Exception as exc:
        _logger.warning("Could not fetch the circuit information: %s", exc)
    return extras


def _circuit_info(fastf1: Any, session: Any) -> Any:
    """The circuit's markers from MultiViewer, with distances where they can be had.

    ``session.get_circuit_info()`` does the same and then places each marker
    along the lap using the fastest lap's position data. When that data is
    broken the whole call fails: the 2026 Monaco race, whose position feed
    stops in lap 5, came back with no corners at all. The markers do not depend
    on the session, so they are fetched on their own and the distances are
    added only if they can be.
    """
    circuit = session.session_info["Meeting"]["Circuit"]
    circuit_key = circuit["Key"]
    if circuit_key == 149 and circuit.get("ShortName") == "Mugello":
        # FastF1's own correction for a key F1 reused.
        circuit_key = 146
    info = fastf1.mvapi.get_circuit_info(year=session.event.year, circuit_key=circuit_key)
    if info is None:
        return None
    try:
        info.add_marker_distance(reference_lap=session.laps.pick_fastest())
    except Exception as exc:
        _logger.warning("Circuit markers kept without distances along the lap: %s", exc)
    return info


def parse_pit_stop_series(data: bytes) -> list[dict[str, Any]]:
    """Each stop F1 reported, in the order it was first reported, as F1 last described it.

    F1's streams send a thing once and after that only what changes. A
    driver's first stop arrives as a list of one, each later stop as a mapping
    keyed by its place in that list, and a correction the same way: keyed by
    the place of the stop it corrects, with the fields that changed and no
    others. So a stop is followed by its driver and its place, and what a
    later line says of it is laid over what an earlier one said. Read line by
    line, a correction that gives a new stationary time and nothing else would
    be a stop with no lap, and be dropped or put beside another stop.

    Never raises, whatever the bytes are: this runs while a fetch is being
    measured, before it is archived, and a broken optional feed must not cost
    the feeds that arrived whole. A line or an entry that cannot be read is
    left out, and so is a stop with neither duration, since there is nothing
    in it to publish. A stop with no lap is kept when it says when it was
    reported: in the 2026 Australian GP F1 sent twenty of its twenty-eight
    stops late and without a lap, and each can still be told by its time
    (``pit_stops`` in f1data/normalize.py). Its ``lap_number`` is ``None``.
    ``time_utc`` is when the stop was first reported, whatever came after.
    """
    stops: dict[tuple[str, int], dict[str, Any]] = {}
    for line in data.decode("utf-8-sig", errors="replace").splitlines():
        # Any exception at all, not the ones a broken line has raised so far:
        # the promise is to the fetch, and a line nested a thousand deep
        # raises RecursionError, which is none of the usual ones.
        try:
            payload = json.loads(line[_STREAM_TIMESTAMP_CHARS:])
            pit_times = payload.get("PitTimes") or {}
            said: list[tuple[tuple[str, int], dict[str, Any]]] = []
            for number, entries in list(pit_times.items()):
                if isinstance(entries, list):
                    placed = list(enumerate(entries))
                elif isinstance(entries, dict):
                    placed = [(int(place), entry) for place, entry in entries.items() if str(place).isdigit()]
                else:
                    continue
                for place, entry in placed:
                    fields = _said_of_a_stop(entry)
                    if fields is not None:
                        said.append(((str(number), place), fields))
        except Exception:
            continue
        for key, fields in said:
            stop = stops.setdefault(
                key,
                {
                    "driver_number": key[0],
                    "lap_number": None,
                    "stationary_ms": None,
                    "pit_lane_ms": None,
                    "time_utc": None,
                },
            )
            for name, value in fields.items():
                # What a line leaves out, or sends empty, stands as it was.
                if value is not None and not (name == "time_utc" and stop["time_utc"] is not None):
                    stop[name] = value
    return [
        stop
        for stop in stops.values()
        if (stop["stationary_ms"] is not None or stop["pit_lane_ms"] is not None)
        and (stop["lap_number"] is not None or stop["time_utc"] is not None)
    ]


def _said_of_a_stop(entry: Any) -> dict[str, Any] | None:
    """What one line says of one stop: each field it gives a readable value for, and ``None`` for the rest."""
    if not isinstance(entry, dict):
        return None
    reported = entry.get("PitStop")
    if not isinstance(reported, dict):
        reported = {}
    number = reported.get("RacingNumber")
    return {
        "driver_number": str(number) if number not in (None, "") else None,
        "lap_number": _int(reported.get("Lap")),
        "stationary_ms": _seconds_to_ms(reported.get("PitStopTime")),
        "pit_lane_ms": _seconds_to_ms(reported.get("PitLaneTime")),
        "time_utc": entry.get("Timestamp") if isinstance(entry.get("Timestamp"), str) else None,
    }


def weather_readings_sent(data: bytes) -> dict[int, frozenset[str]]:
    """Which readings each line of F1's weather feed gives, by the line's time in milliseconds.

    A reading is given when the line has it and it reads as a number, or for
    ``Rainfall`` as one of the two values F1 sends. FastF1 writes 0 for one
    that is missing or empty, so that a sensor that was off comes out as a
    track at 0 degrees, still air and no rain; this is how ``weather`` in
    f1data/normalize.py tells those from readings. Two lines with one time
    give what both give. Never raises: a line that cannot be read gives
    nothing, and a sample with no line to its name is published without
    readings.
    """
    sent: dict[int, frozenset[str]] = {}
    for line in data.decode("utf-8-sig", errors="replace").splitlines():
        try:
            clock = _STREAM_CLOCK.match(line[:_STREAM_TIMESTAMP_CHARS])
            payload = json.loads(line[_STREAM_TIMESTAMP_CHARS:])
            if clock is None or not isinstance(payload, dict):
                continue
            hours, minutes, seconds, milliseconds = (int(part) for part in clock.groups())
            moment = ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds
            given = {name for name in _WEATHER_NUMBERS if _number(_as_number(payload.get(name))) is not None}
            if payload.get("Rainfall") in ("0", "1"):
                given.add("Rainfall")
        except Exception:
            continue
        sent[moment] = sent[moment] & frozenset(given) if moment in sent else frozenset(given)
    return sent


def _as_number(value: Any) -> float | None:
    """A reading F1 sends as text, as a number, or ``None`` for anything ``float`` would not take as one."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except (ValueError, OverflowError):
        return None


def circuit_corner_count(data: bytes) -> int:
    """How many corners with a position an archived circuit-info file holds. Never raises."""
    try:
        corners = json.loads(data.decode("utf-8", errors="replace")).get("corners")
        if not isinstance(corners, list):
            return 0
        return sum(
            1
            for corner in corners
            if isinstance(corner, dict)
            and isinstance(corner.get("x"), (int, float))
            and isinstance(corner.get("y"), (int, float))
        )
    except Exception:
        return 0


def circuit_info_json(info: Any) -> dict[str, Any]:
    """FastF1's circuit information as plain JSON."""
    return {
        "rotation": _number(getattr(info, "rotation", None)),
        "corners": _markers(getattr(info, "corners", None)),
        "marshal_lights": _markers(getattr(info, "marshal_lights", None)),
        "marshal_sectors": _markers(getattr(info, "marshal_sectors", None)),
    }


def _markers(frame: Any) -> list[dict[str, Any]]:
    if frame is None or len(frame) == 0:
        return []
    return [
        {
            "number": _int(row.get("Number")),
            "letter": str(row.get("Letter") or ""),
            "x": _number(row.get("X")),
            "y": _number(row.get("Y")),
            "angle": _number(row.get("Angle")),
            "distance_m": _number(row.get("Distance")),
        }
        for _, row in frame.iterrows()
    ]


def _seconds_to_ms(value: Any) -> int | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: a whole number too large for a float, such as 10**400.
        return None
    # "Infinity" and "NaN" are floats to Python and durations to nobody, and
    # so is anything longer than a day: "1e308" is finite until it is
    # multiplied. The comparison is false for NaN.
    return round(seconds * 1000) if 0 <= seconds <= _LONGEST_DURATION_SECONDS else None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(number, 3) if math.isfinite(number) else None


def _dump(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
