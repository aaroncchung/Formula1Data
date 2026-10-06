"""Data a build needs that FastF1 does not load with a session.

A build may not fetch from a host that might refuse it, so anything of this
kind is fetched and archived with the session
(docs/architecture-review-findings.md, section 6, rule 4):

* ``PitStopSeries``, the F1 feed with each stop's stationary time and
  pit-lane time. FastF1 does not parse it (AR-16).
* The circuit's corner positions, which FastF1 takes from MultiViewer (AR-17).
"""

from __future__ import annotations

import json
import logging
from typing import Any

PIT_STOP_SERIES = "PitStopSeries.jsonStream"
CIRCUIT_INFO = "circuit-info.json"

# Each line of an F1 stream starts with the session time, as HH:MM:SS.mmm.
_STREAM_TIMESTAMP_CHARS = 12

_logger = logging.getLogger(__name__)


def fetch_extras(fastf1: Any, session: Any, archive_path: str) -> dict[str, bytes]:
    """Fetch what is there, by name. A missing entry means it did not arrive.

    Called inside the fetch's cache and request log, so both requests are
    rate-limited and recorded like FastF1's own.
    """
    from fastf1 import _api

    extras: dict[str, bytes] = {}
    try:
        response = fastf1.Cache.requests_get(
            f"{_api.base_url}/static/{archive_path}{PIT_STOP_SERIES}", headers=_api.headers
        )
        # F1 answers 403 for a feed it does not hold, as it did for races
        # before late 2024.
        if response.status_code == 200 and response.content:
            extras[PIT_STOP_SERIES] = response.content
    except Exception as exc:
        _logger.warning("Could not fetch %s: %s", PIT_STOP_SERIES, exc)

    try:
        info = session.get_circuit_info()
        if info is not None:
            extras[CIRCUIT_INFO] = _dump(circuit_info_json(info))
    except Exception as exc:
        _logger.warning("Could not fetch the circuit information: %s", exc)
    return extras


def parse_pit_stop_series(data: bytes) -> list[dict[str, Any]]:
    """Each stop F1 reported, in the order it was reported.

    A driver's first stop arrives as a list of one and each later stop as a
    mapping keyed by its index, the way F1's streams send additions.
    """
    stops: list[dict[str, Any]] = []
    for line in data.decode("utf-8-sig").splitlines():
        if len(line) <= _STREAM_TIMESTAMP_CHARS:
            continue
        try:
            payload = json.loads(line[_STREAM_TIMESTAMP_CHARS:])
        except ValueError:
            continue
        for number, entries in (payload.get("PitTimes") or {}).items():
            for entry in entries if isinstance(entries, list) else list(entries.values()):
                stop = (entry or {}).get("PitStop") or {}
                stops.append(
                    {
                        "driver_number": str(stop.get("RacingNumber") or number),
                        "lap_number": _int(stop.get("Lap")),
                        "stationary_ms": _seconds_to_ms(stop.get("PitStopTime")),
                        "pit_lane_ms": _seconds_to_ms(stop.get("PitLaneTime")),
                        "time_utc": entry.get("Timestamp"),
                    }
                )
    return stops


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
        return round(float(value) * 1000)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 3) if number == number else None


def _dump(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
