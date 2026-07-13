from datetime import date
import math
from typing import Any

from app.ingestion.result_validation import (
    InvalidSessionResultsError,
    is_final_session,
    validate_final_results,
)

try:
    import pandas as pd
except ImportError:  # Allows metadata helpers to run without backend ingestion deps installed.
    pd = None


SESSION_CODE_BY_NAME = {
    "Practice 1": "FP1",
    "Practice 2": "FP2",
    "Practice 3": "FP3",
    "Qualifying": "Q",
    "Sprint": "S",
    "Sprint Qualifying": "SQ",
    "Sprint Shootout": "SQ",
    "Race": "R",
}
SESSION_CODE_BY_NORMALIZED_NAME = {name.lower(): code for name, code in SESSION_CODE_BY_NAME.items()}
MAX_INGESTED_TELEMETRY_SAMPLES_PER_LAP = 300


class IncompleteFastF1SessionError(RuntimeError):
    """Raised when FastF1 returns a session shell without the required timing data."""


def session_code_for_name(name: Any) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    return SESSION_CODE_BY_NAME.get(raw) or SESSION_CODE_BY_NORMALIZED_NAME.get(raw.lower()) or raw.upper()


def sessions_available_from_event(event: Any) -> list[str]:
    sessions = []
    for index in range(1, 6):
        name = _get(event, f"Session{index}")
        if _is_missing(name):
            continue
        code = session_code_for_name(name)
        if code and code not in sessions:
            sessions.append(code)
    return sessions or ["R"]


def selected_session_codes(
    event: Any,
    sessions: list[str] | None = None,
    races_only: bool = False,
) -> list[str]:
    available = sessions_available_from_event(event)
    requested = {"R"} if races_only else requested_session_codes(sessions)
    if requested is None:
        return available
    return [code for code in available if code in requested]


def requested_session_codes(sessions: list[str] | None) -> set[str] | None:
    if not sessions:
        return None
    return {session_code_for_name(session) for session in sessions if session_code_for_name(session)}


def session_start_time_from_event(event: Any, session_code: str) -> str | None:
    code = session_code_for_name(session_code)
    for index in range(1, 6):
        name = _get(event, f"Session{index}")
        if _is_missing(name) or session_code_for_name(name) != code:
            continue
        value = _get(event, f"Session{index}DateUtc")
        if _is_missing(value):
            value = _get(event, f"Session{index}Date")
        return _iso_or_none(value)
    return None


def normalize_fastf1_schedule(year: int, schedule: Any) -> dict[str, Any]:
    meetings = []
    for _, row in schedule.iterrows():
        round_number = _safe_int(_get(row, "RoundNumber"), default=0) or 0
        if round_number <= 0:
            continue
        event_name = str(_get(row, "EventName", "") or "")
        if not event_name:
            continue
        country = str(_get(row, "Country", "") or "")
        location = str(_get(row, "Location", "") or "")
        circuit_name = str(_get(row, "CircuitName", location or event_name) or event_name)
        meetings.append(
            {
                "meeting_id": f"{year}-{round_number:02d}-{_slug(event_name)}",
                "year": year,
                "round": round_number,
                "name": event_name,
                "official_name": _none_if_missing(_get(row, "OfficialEventName", event_name)),
                "circuit": {
                    "circuit_id": _slug(circuit_name),
                    "name": circuit_name,
                    "country": country,
                    "location": location,
                },
                "start_date": _event_date(row),
                "country": country,
                "sessions_available": sessions_available_from_event(row),
                "is_ingested": False,
                "is_sample": False,
            }
        )

    return {
        "seasons": [
            {
                "year": year,
                "meeting_count": len(meetings),
                "ingested_meeting_count": 0,
                "is_sample": False,
            }
        ],
        "meetings": meetings,
        "sessions": [],
        "session_data": {},
    }


def normalize_fastf1_session(year: int, event_name: str, session_name: str, session: Any) -> dict[str, Any]:
    event = getattr(session, "event", {})
    round_number = _safe_int(_get(event, "RoundNumber"), default=0)
    country = str(_get(event, "Country", "") or "")
    location = str(_get(event, "Location", "") or "")
    meeting_name = str(_get(event, "EventName", event_name) or event_name)
    circuit_name = str(_get(event, "CircuitName", location or meeting_name) or meeting_name)
    session_type = str(getattr(session, "name", session_name) or session_name)
    code = session_code_for_name(session_name)
    if code not in sessions_available_from_event(event):
        code = session_code_for_name(session_type)
    session_id = f"{year}-{round_number:02d}-{code.lower()}"
    meeting_id = f"{year}-{round_number:02d}-{_slug(meeting_name)}"

    drivers = _drivers(session)
    laps = _laps(session, session_id)
    stints = _stints(laps, session_id)
    pit_stops = _pit_stops(_session_frame(session, "laps"), session_id)
    weather = _weather(session, session_id)
    race_control = _race_control(session, session_id)
    results = _results(session, session_id, required=is_final_session(session_id, code))
    telemetry = _telemetry(session, session_id)

    dataset = {
        "seasons": [
            {
                "year": year,
                "meeting_count": 1,
                "ingested_meeting_count": 1,
                "is_sample": False,
            }
        ],
        "meetings": [
            {
                "meeting_id": meeting_id,
                "year": year,
                "round": round_number,
                "name": meeting_name,
                "official_name": str(_get(event, "OfficialEventName", meeting_name) or meeting_name),
                "circuit": {
                    "circuit_id": _slug(circuit_name),
                    "name": circuit_name,
                    "country": country,
                    "location": location,
                },
                "start_date": _event_date(event),
                "country": country,
                "sessions_available": sessions_available_from_event(event),
                "is_ingested": True,
                "is_sample": False,
            }
        ],
        "sessions": [
            {
                "session_id": session_id,
                "year": year,
                "round": round_number,
                "meeting_id": meeting_id,
                "name": session_type,
                "type": code,
                "start_time": session_start_time_from_event(event, code),
                "end_time": None,
                "status": "available",
                "is_sample": False,
            }
        ],
        "session_data": {
            session_id: {
                "summary": {
                    "session_id": session_id,
                    "meeting": meeting_name,
                    "session": session_type,
                    "year": year,
                    "round": round_number,
                    "circuit": circuit_name,
                    "country": country,
                    "driver_count": len(drivers),
                    "lap_count": len(laps),
                    "weather_summary": _weather_summary(weather),
                    "is_sample": False,
                    "available_sections": [
                        "drivers",
                        "laps",
                        "results",
                        "stints",
                        "pit_stops",
                        "weather",
                        "race_control",
                        "telemetry",
                    ],
                },
                "drivers": drivers,
                "laps": laps,
                "stints": stints,
                "pit_stops": pit_stops,
                "weather": weather,
                "race_control": race_control,
                "results": results,
                "telemetry": telemetry,
            }
        },
    }
    return dataset


def _drivers(session: Any) -> list[dict[str, Any]]:
    results = _session_frame(session, "results")
    if results is None or results.empty:
        return []
    drivers = []
    for _, row in results.iterrows():
        code = str(row.get("Abbreviation") or row.get("BroadcastName") or "").strip()
        if not code:
            continue
        team_name = str(row.get("TeamName") or "Unknown")
        color = row.get("TeamColor")
        drivers.append(
            {
                "driver_id": code.lower(),
                "code": code,
                "full_name": str(row.get("FullName") or code),
                "number": _safe_int(row.get("DriverNumber"), default=None),
                "team": {
                    "team_id": _slug(team_name),
                    "name": team_name,
                    "color": f"#{color}" if color and not str(color).startswith("#") else color,
                },
                "country": row.get("CountryCode"),
            }
        )
    return drivers


def _laps(session: Any, session_id: str) -> list[dict[str, Any]]:
    laps_df = _session_frame(session, "laps", required=True)
    if laps_df is None or laps_df.empty:
        raise IncompleteFastF1SessionError(
            f"FastF1 did not load lap data for {session_id}. "
            "The upstream session data may be unavailable or blocked from this runner."
        )
    rows = []
    for _, row in laps_df.iterrows():
        rows.append(
            {
                "session_id": session_id,
                "driver_code": str(row.get("Driver") or ""),
                "lap_number": _safe_int(row.get("LapNumber"), default=0),
                "lap_time_ms": _timedelta_ms(row.get("LapTime")),
                "sector_1_ms": _timedelta_ms(row.get("Sector1Time")),
                "sector_2_ms": _timedelta_ms(row.get("Sector2Time")),
                "sector_3_ms": _timedelta_ms(row.get("Sector3Time")),
                "compound": row.get("Compound"),
                "tyre_age": _safe_int(row.get("TyreLife"), default=None),
                "stint": _safe_int(row.get("Stint"), default=None),
                "position": _safe_int(row.get("Position"), default=None),
                "is_pit_in_lap": pd.notna(row.get("PitInTime")),
                "is_pit_out_lap": pd.notna(row.get("PitOutTime")),
                "is_deleted": _bool_or_none(row.get("Deleted")) or False,
                "is_accurate": _bool_or_none(row.get("IsAccurate"))
                if _bool_or_none(row.get("IsAccurate")) is not None
                else True,
                "track_status": str(row.get("TrackStatus") or ""),
            }
        )
    return rows


def _stints(laps: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for lap in laps:
        key = (
            lap.get("driver_code", ""),
            int(lap.get("stint") or 0),
            str(lap.get("compound") or "UNKNOWN"),
        )
        groups.setdefault(key, []).append(lap)
    rows = []
    for (driver, stint, compound), group in groups.items():
        lap_numbers = [int(lap["lap_number"]) for lap in group if lap.get("lap_number")]
        if not lap_numbers:
            continue
        rows.append(
            {
                "session_id": session_id,
                "driver_code": driver,
                "stint": stint,
                "compound": compound,
                "start_lap": min(lap_numbers),
                "end_lap": max(lap_numbers),
                "lap_count": len(lap_numbers),
            }
        )
    return rows


def _pit_stops(laps_df: Any, session_id: str) -> list[dict[str, Any]]:
    """Build pit-lane transit records from matching FastF1 pit-in/out timestamps.

    FastF1 exposes the pit-entry timestamp on the in-lap and the pit-exit timestamp on
    the following lap. Their difference is total pit-lane time, not stationary service
    time. Keeping the existing ``duration_ms`` field preserves compatibility while
    finally populating it with the best duration available in the upstream timing data.
    """
    if laps_df is None or laps_df.empty:
        return []

    by_driver: dict[str, list[Any]] = {}
    for _, lap in laps_df.iterrows():
        driver = str(lap.get("Driver") or "").upper()
        if driver:
            by_driver.setdefault(driver, []).append(lap)

    stops: list[dict[str, Any]] = []
    for driver, driver_laps in by_driver.items():
        ordered = sorted(
            driver_laps,
            key=lambda lap: _safe_int(lap.get("LapNumber"), default=0) or 0,
        )
        for index, lap in enumerate(ordered):
            pit_in = lap.get("PitInTime")
            if _is_missing(pit_in):
                continue

            pit_out = None
            current_lap_number = _safe_int(lap.get("LapNumber"), default=0) or 0
            if index + 1 < len(ordered):
                candidate = ordered[index + 1]
                candidate_lap_number = _safe_int(candidate.get("LapNumber"), default=0) or 0
                candidate_out = candidate.get("PitOutTime")
                if candidate_lap_number == current_lap_number + 1 and not _is_missing(candidate_out):
                    try:
                        if candidate_out >= pit_in:
                            pit_out = candidate_out
                    except TypeError:
                        pit_out = None

            duration_ms = None
            if pit_out is not None:
                try:
                    duration_ms = _timedelta_ms(pit_out - pit_in)
                except TypeError:
                    duration_ms = None
            stops.append(
                {
                    "session_id": session_id,
                    "driver_code": driver,
                    "lap_number": _safe_int(lap.get("LapNumber"), default=0),
                    "duration_ms": duration_ms,
                    "local_time": str(pit_in),
                }
            )
    return stops


def _weather(session: Any, session_id: str) -> list[dict[str, Any]]:
    weather_df = _session_frame(session, "weather_data")
    if weather_df is None or weather_df.empty:
        return []
    rows = []
    for index, row in weather_df.reset_index(drop=True).iterrows():
        rows.append(
            {
                "session_id": session_id,
                "lap_number": None,
                "timestamp": str(row.get("Time")) if row.get("Time") is not None else str(index),
                "air_temp_c": _float_or_none(row.get("AirTemp")),
                "track_temp_c": _float_or_none(row.get("TrackTemp")),
                "humidity_pct": _float_or_none(row.get("Humidity")),
                "rainfall": _bool_or_none(row.get("Rainfall")) or False,
                "wind_speed_kph": _float_or_none(row.get("WindSpeed")),
            }
        )
    return rows[:: max(1, len(rows) // 25)]


def _race_control(session: Any, session_id: str) -> list[dict[str, Any]]:
    messages = _session_frame(session, "race_control_messages")
    if messages is None or messages.empty:
        return []
    rows = []
    for _, row in messages.iterrows():
        rows.append(
            {
                "session_id": session_id,
                "lap_number": _safe_int(row.get("Lap"), default=None),
                "timestamp": str(row.get("Time")) if row.get("Time") is not None else None,
                "category": str(row.get("Category") or "Message"),
                "message": str(row.get("Message") or ""),
                "flag": row.get("Flag"),
                "scope": row.get("Scope"),
            }
        )
    return rows


def _results(session: Any, session_id: str, required: bool = False) -> list[dict[str, Any]]:
    results = _session_frame(session, "results", required=required)
    if results is None or results.empty:
        if required:
            raise IncompleteFastF1SessionError(
                f"FastF1 did not provide a final classification for {session_id}."
            )
        return []
    rows = []
    for _, row in results.iterrows():
        classified_position = _string_or_none(
            row.get("ClassifiedPosition")
            if not _is_missing(row.get("ClassifiedPosition"))
            else row.get("Position")
        )
        rows.append(
            {
                "session_id": session_id,
                "position": _safe_int(row.get("Position"), default=None if required else 0),
                "driver_code": str(row.get("Abbreviation") or ""),
                "classified_position": classified_position,
                "status": _string_or_none(row.get("Status")),
                "points": _float_or_none(row.get("Points")),
                "grid": _safe_int(row.get("GridPosition"), default=None),
                "gap": _string_or_none(row.get("Time")),
                "laps": _safe_int(row.get("Laps"), default=None),
            }
        )
    if required:
        try:
            validate_final_results(session_id, rows)
        except InvalidSessionResultsError as exc:
            raise IncompleteFastF1SessionError(str(exc)) from exc
    return rows


def _telemetry(session: Any, session_id: str) -> list[dict[str, Any]]:
    laps_df = _session_frame(session, "laps")
    if laps_df is None or laps_df.empty:
        return []
    telemetry_rows = []
    iterator = getattr(laps_df, "iterlaps", None)
    try:
        laps = iterator() if callable(iterator) else laps_df.iterrows()
    except Exception:
        laps = laps_df.iterrows()

    seen: set[tuple[str, int]] = set()
    for _, lap in laps:
        driver = str(lap.get("Driver") or "").upper()
        lap_number = _safe_int(lap.get("LapNumber"), default=0) or 0
        if not driver or lap_number <= 0 or (_bool_or_none(lap.get("Deleted")) or False):
            continue
        key = (driver, lap_number)
        if key in seen:
            continue
        seen.add(key)
        telemetry = _lap_telemetry(lap)
        if telemetry is None or telemetry.empty:
            continue
        for _, row in _bounded_frame(telemetry, MAX_INGESTED_TELEMETRY_SAMPLES_PER_LAP).iterrows():
            telemetry_rows.append(
                {
                    "session_id": session_id,
                    "driver_code": driver,
                    "lap_number": lap_number,
                    "distance_m": _float_or_none(row.get("Distance")) or 0,
                    "speed_kph": _float_or_none(row.get("Speed")),
                    "throttle_pct": _float_or_none(row.get("Throttle")),
                    "brake": _bool_or_none(row.get("Brake")),
                    "rpm": _safe_int(row.get("RPM"), default=None),
                    "gear": _safe_int(row.get("nGear"), default=None),
                    "drs": _safe_int(row.get("DRS"), default=None),
                    "x": _float_or_none(row.get("X")),
                    "y": _float_or_none(row.get("Y")),
                    "relative_time_ms": _timedelta_ms(row.get("Time")),
                    "session_time_ms": _timedelta_ms(row.get("SessionTime")),
                }
            )
    return telemetry_rows


def _lap_telemetry(lap: Any) -> Any:
    try:
        telemetry = lap.get_telemetry()
        if telemetry is not None and not telemetry.empty:
            return telemetry
    except Exception:
        pass

    try:
        telemetry = lap.get_car_data()
    except Exception:
        return None
    if telemetry is None or telemetry.empty:
        return telemetry
    if "Distance" not in telemetry.columns:
        try:
            telemetry = telemetry.add_distance()
        except Exception:
            return None
    return telemetry


def _bounded_frame(frame: Any, limit: int) -> Any:
    """Evenly sample a frame, retaining both endpoints and never exceeding ``limit``."""
    if limit <= 0:
        return frame.iloc[0:0]
    if limit == 1:
        return frame.iloc[[0]]
    if len(frame) <= limit:
        return frame
    indexes = sorted(
        {
            round(index * (len(frame) - 1) / (limit - 1))
            for index in range(limit)
        }
    )
    # Floating point rounding can theoretically create a duplicate; fill any gap
    # with a deterministic stride while respecting the hard cap.
    if len(indexes) < limit:
        step = max(1, math.floor(len(frame) / limit))
        indexes = sorted(set(indexes).union(range(0, len(frame), step)))[:limit]
        indexes[-1] = len(frame) - 1
    return frame.iloc[indexes]


def _session_frame(session: Any, attr: str, required: bool = False) -> Any:
    try:
        return getattr(session, attr)
    except Exception as exc:
        if required:
            raise IncompleteFastF1SessionError(
                f"FastF1 did not load {attr} for this session. "
                "The upstream session data may be unavailable or blocked from this runner."
            ) from exc
        return _empty_frame()


def _empty_frame() -> Any:
    if pd is None:
        return None
    return pd.DataFrame()


def _weather_summary(weather: list[dict[str, Any]]) -> str:
    if not weather:
        return "Weather data unavailable"
    air = [row["air_temp_c"] for row in weather if row.get("air_temp_c") is not None]
    track = [row["track_temp_c"] for row in weather if row.get("track_temp_c") is not None]
    rainfall = any(row.get("rainfall") for row in weather)
    parts = []
    if air:
        parts.append(f"air {min(air):.1f}-{max(air):.1f}C")
    if track:
        parts.append(f"track {min(track):.1f}-{max(track):.1f}C")
    parts.append("rain" if rainfall else "dry")
    return ", ".join(parts)


def _event_date(event: Any) -> str | None:
    value = _get(event, "EventDate")
    if _is_missing(value):
        value = _get(event, "Session5Date")
    if _is_missing(value):
        return None
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except Exception:
        return getattr(obj, key, default)


def _timedelta_ms(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "total_seconds"):
        return int(value.total_seconds() * 1000)
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int | None) -> int | None:
    if _is_missing(value):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_or_none(value: Any) -> bool | None:
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        normalized = str(value).strip().lower()
        if normalized in {"true", "yes", "on"}:
            return True
        if normalized in {"false", "no", "off"}:
            return False
    return None


def _string_or_none(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return str(value)


def _iso_or_none(value: Any) -> str | None:
    if _is_missing(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")


def _none_if_missing(value: Any) -> Any:
    return None if _is_missing(value) else value


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if pd is None:
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False

