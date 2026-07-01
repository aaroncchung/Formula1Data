from datetime import date
from typing import Any

import pandas as pd


def normalize_fastf1_session(year: int, event_name: str, session_name: str, session: Any) -> dict[str, Any]:
    event = getattr(session, "event", {})
    round_number = _safe_int(_get(event, "RoundNumber"), default=0)
    country = str(_get(event, "Country", "") or "")
    location = str(_get(event, "Location", "") or "")
    meeting_name = str(_get(event, "EventName", event_name) or event_name)
    circuit_name = str(_get(event, "CircuitName", location or meeting_name) or meeting_name)
    session_type = str(getattr(session, "name", session_name) or session_name)
    code = session_name.upper()
    session_id = f"{year}-{round_number:02d}-{code.lower()}"
    meeting_id = f"{year}-{round_number:02d}-{_slug(meeting_name)}"

    drivers = _drivers(session)
    laps = _laps(session, session_id)
    stints = _stints(laps, session_id)
    pit_stops = _pit_stops(laps, session_id)
    weather = _weather(session, session_id)
    race_control = _race_control(session, session_id)
    results = _results(session, session_id)
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
                "sessions_available": ["FP1", "FP2", "FP3", "Q", "R"],
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
                "start_time": _iso_or_none(_get(event, "Session5DateUtc")),
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
    results = getattr(session, "results", pd.DataFrame())
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
    laps_df = getattr(session, "laps", pd.DataFrame())
    if laps_df is None or laps_df.empty:
        return []
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
                "is_deleted": bool(row.get("Deleted", False)),
                "is_accurate": bool(row.get("IsAccurate", True)),
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


def _pit_stops(laps: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    return [
        {
            "session_id": session_id,
            "driver_code": lap["driver_code"],
            "lap_number": lap["lap_number"],
            "duration_ms": None,
            "local_time": None,
        }
        for lap in laps
        if lap.get("is_pit_in_lap")
    ]


def _weather(session: Any, session_id: str) -> list[dict[str, Any]]:
    weather_df = getattr(session, "weather_data", pd.DataFrame())
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
                "rainfall": bool(row.get("Rainfall", False)),
                "wind_speed_kph": _float_or_none(row.get("WindSpeed")),
            }
        )
    return rows[:: max(1, len(rows) // 25)]


def _race_control(session: Any, session_id: str) -> list[dict[str, Any]]:
    messages = getattr(session, "race_control_messages", pd.DataFrame())
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


def _results(session: Any, session_id: str) -> list[dict[str, Any]]:
    results = getattr(session, "results", pd.DataFrame())
    if results is None or results.empty:
        return []
    rows = []
    for _, row in results.iterrows():
        rows.append(
            {
                "session_id": session_id,
                "position": _safe_int(row.get("Position"), default=0),
                "driver_code": str(row.get("Abbreviation") or ""),
                "classified_position": str(row.get("ClassifiedPosition") or row.get("Position") or ""),
                "status": row.get("Status"),
                "points": _float_or_none(row.get("Points")),
                "grid": _safe_int(row.get("GridPosition"), default=None),
                "gap": str(row.get("Time") or ""),
                "laps": _safe_int(row.get("Laps"), default=None),
            }
        )
    return rows


def _telemetry(session: Any, session_id: str) -> list[dict[str, Any]]:
    laps_df = getattr(session, "laps", pd.DataFrame())
    if laps_df is None or laps_df.empty:
        return []
    telemetry_rows = []
    fastest = laps_df.pick_fastest()
    selected = [fastest]
    for _, lap in laps_df.pick_drivers(laps_df["Driver"].dropna().unique()[:2]).iterrows():
        if lap.get("LapTime") == fastest.get("LapTime"):
            continue
        selected.append(lap)
        if len(selected) >= 2:
            break
    for lap in selected:
        try:
            telemetry = lap.get_telemetry()
        except Exception:
            continue
        step = max(1, len(telemetry) // 250)
        for _, row in telemetry.iloc[::step].iterrows():
            telemetry_rows.append(
                {
                    "session_id": session_id,
                    "driver_code": str(lap.get("Driver") or ""),
                    "lap_number": _safe_int(lap.get("LapNumber"), default=0),
                    "distance_m": _float_or_none(row.get("Distance")) or 0,
                    "speed_kph": _float_or_none(row.get("Speed")),
                    "throttle_pct": _float_or_none(row.get("Throttle")),
                    "brake": bool(row.get("Brake")) if row.get("Brake") is not None else None,
                    "rpm": _safe_int(row.get("RPM"), default=None),
                    "gear": _safe_int(row.get("nGear"), default=None),
                    "drs": _safe_int(row.get("DRS"), default=None),
                    "x": _float_or_none(row.get("X")),
                    "y": _float_or_none(row.get("Y")),
                    "relative_time_ms": _timedelta_ms(row.get("Time")),
                }
            )
    return telemetry_rows


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
    value = _get(event, "EventDate") or _get(event, "Session5Date")
    if value is None:
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
    if value is None or pd.isna(value):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _iso_or_none(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")

