"""A small race, complete enough to build every artifact from.

Three drivers, twelve laps of a circular track. It carries what FastF1 leaves
on a loaded session, in FastF1's own types (pandas durations, floats for whole
numbers, ``NaN`` and ``NaT`` for what is missing), because turning those into
clean rows is the thing under test.

Driver 1 (AAA) stops on lap 5. Driver 3 (CCC) retires after lap 9. The two
telemetry feeds tick at different rates, as F1's do, so that every lap has to
be merged.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from f1data.classification import Classification
from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES
from f1data.identity import SessionIdentity

CLOCK_ZERO = pd.Timestamp("2026-06-28 12:00:00")
RACE_START_SECONDS = 600.0
LAPS = 12
TRACK_LENGTH_M = 5000.0
# Position is in tenths of a metre, as F1 sends it.
TRACK_RADIUS = TRACK_LENGTH_M * 10 / (2 * np.pi)

DRIVERS = {
    "1": {"code": "AAA", "name": "Anna Able", "team": "Alpha Racing", "colour": "FF8000", "lap_seconds": 80.0},
    "2": {"code": "BBB", "name": "Ben Baker", "team": "Alpha Racing", "colour": "FF8000", "lap_seconds": 80.5},
    "3": {"code": "CCC", "name": "Cara Cole", "team": "Beta GP", "colour": "0090FF", "lap_seconds": 81.0},
}
PIT_LAP = 5
PIT_LOSS_SECONDS = 20.0
RETIRED_AFTER = {"3": 9}

IDENTITY = SessionIdentity(
    session_key=9001,
    meeting_key=801,
    year=2026,
    session_type="R",
    session_name="Race",
    start_time_utc="2026-06-28T12:10:00Z",
    meeting_name="Ring Grand Prix",
    meeting_official_name="FORMULA 1 RING GRAND PRIX 2026",
    location="Ringstadt",
    country="Ringland",
    circuit_key=77,
    circuit_name="The Ring",
    archive_path="2026/2026-06-28_Ring_Grand_Prix/2026-06-28_Race/",
    round_at_fetch=8,
)

# The start line is at (0, TRACK_RADIUS) and the cars run clockwise from it.
CORNERS = [
    {"number": 1, "letter": "", "x": TRACK_RADIUS, "y": 0.0, "angle": 0.0, "distance_m": 1250.0},
    {"number": 2, "letter": "A", "x": 0.0, "y": -TRACK_RADIUS, "angle": -90.0, "distance_m": 2500.0},
    {"number": 3, "letter": "", "x": -TRACK_RADIUS, "y": 0.0, "angle": 180.0, "distance_m": 3750.0},
]


def extras(corner_distances: bool = True, pit_stops: bool = True, corners: bool = True) -> dict[str, bytes]:
    """The feeds archived beside the session."""
    found: dict[str, bytes] = {}
    if pit_stops:
        found[PIT_STOP_SERIES] = (
            b'01:00:00.000{"PitTimes":{"1":[{"Timestamp":"2026-06-28T12:16:00.000Z",'
            b'"PitStop":{"RacingNumber":"1","PitStopTime":"2.4","PitLaneTime":"19.900","Lap":"5"}}]}}\r\n'
        )
    if corners:
        listed = [
            corner if corner_distances else {**corner, "distance_m": None} for corner in CORNERS
        ]
        found[CIRCUIT_INFO] = json.dumps({"rotation": 12.0, "corners": listed}).encode()
    return found


def classification() -> Classification:
    """Jolpica's result: AAA wins, BBB four seconds back, CCC retired after nine laps."""
    rows = [
        _classified("1", "AAA", "Anna", "Able", "Alpha Racing", 1, "1", 2, "Finished", 25, 990_500, 12),
        _classified("2", "BBB", "Ben", "Baker", "Alpha Racing", 2, "2", 1, "Finished", 18, 4_000, 12),
        _classified("3", "CCC", "Cara", "Cole", "Beta GP", 3, "R", 3, "Retired", 0, None, 9),
    ]
    return Classification(rows=rows, fingerprint="sha256:" + "a" * 64)


def _classified(number, code, given, family, team, position, text, grid, status, points, time_ms, laps):
    return {
        "number": int(number),
        "driverCode": code,
        "givenName": given,
        "familyName": family,
        "constructorName": team,
        "position": position,
        "positionText": text,
        "grid": grid,
        "status": status,
        "points": points,
        "totalRaceTime": time_ms,
        "laps": laps,
    }


def make_race(position_until: float | None = None, drs: bool = False) -> SimpleNamespace:
    """A loaded session. ``position_until`` stops the position feed at that session time, in seconds."""
    lap_rows: list[dict[str, Any]] = []
    ends: dict[str, float] = {}
    for number, driver in DRIVERS.items():
        moment = RACE_START_SECONDS
        stint = 1
        for lap in range(1, RETIRED_AFTER.get(number, LAPS) + 1):
            seconds = driver["lap_seconds"] + 0.011 * lap
            pits = number == "1" and lap == PIT_LAP
            leaves = number == "1" and lap == PIT_LAP + 1
            if pits or leaves:
                seconds += PIT_LOSS_SECONDS / 2
            if leaves:
                stint += 1
            lap_rows.append(
                {
                    "Time": _duration(moment + seconds),
                    "Driver": driver["code"],
                    "DriverNumber": number,
                    # F1 does not time the first lap of a race.
                    "LapTime": pd.NaT if lap == 1 else _duration(seconds),
                    "LapNumber": float(lap),
                    "Stint": float(stint),
                    "PitOutTime": _duration(moment + 12.0) if leaves else pd.NaT,
                    "PitInTime": _duration(moment + seconds - 8.0) if pits else pd.NaT,
                    "Sector1Time": pd.NaT if lap == 1 else _duration(seconds * 0.3),
                    "Sector2Time": _duration(seconds * 0.4),
                    "Sector3Time": _duration(seconds * 0.3),
                    # What FastF1 leaves when F1 reports no compound.
                    "Compound": None if (number, stint) == ("1", 2) and lap > 9 else ("MEDIUM" if stint == 1 else "HARD"),
                    "TyreLife": np.nan if (number, stint) == ("1", 2) else float(lap),
                    "LapStartTime": _duration(moment),
                    "TrackStatus": "12" if lap == 3 else "1",
                    "Position": float(list(DRIVERS).index(number) + 1),
                    "Deleted": number == "2" and lap == 7,
                    "FastF1Generated": False,
                    "IsAccurate": lap != 1 and not pits and not leaves,
                }
            )
            moment += seconds
        ends[number] = moment
    # FastF1 adds a lap for a car that stopped on track.
    for number, last_lap in RETIRED_AFTER.items():
        lap_rows.append(
            {
                **{key: (pd.NaT if isinstance(value, pd.Timedelta) else value) for key, value in lap_rows[-1].items()},
                "Driver": DRIVERS[number]["code"],
                "DriverNumber": number,
                "LapNumber": float(last_lap + 1),
                "LapStartTime": _duration(ends[number]),
                "Time": _duration(ends[number] + 150.0),
                "LapTime": pd.NaT,
                "Position": np.nan,
                "TrackStatus": "1",
                "FastF1Generated": True,
                "IsAccurate": False,
                "Deleted": False,
            }
        )
    laps = pd.DataFrame(lap_rows)

    session_end = max(ends.values()) + 200.0
    car_data, pos_data = {}, {}
    for index, (number, driver) in enumerate(DRIVERS.items()):
        car_times = np.arange(0.0, session_end, 0.25) + 0.013 * index
        # Slowest at the start line and at the three corners: a quarter, a half and three quarters round.
        phase = 2 * np.pi * (car_times - RACE_START_SECONDS) / driver["lap_seconds"]
        # Averaging one lap of the track per lap time, so that a lap is a closed loop.
        cruising = TRACK_LENGTH_M / driver["lap_seconds"] * 3.6
        speed = np.where(car_times < RACE_START_SECONDS, 0.0, cruising * (1 - np.cos(4 * phase) / 3))
        speed = np.rint(speed)
        car_data[number] = pd.DataFrame(
            {
                "Date": CLOCK_ZERO + pd.to_timedelta(np.rint(car_times * 1000), unit="ms"),
                "SessionTime": pd.to_timedelta(np.rint(car_times * 1000), unit="ms"),
                "Speed": speed,
                "RPM": np.rint(6000.0 + 20.0 * speed),
                "nGear": np.clip((speed // 45).astype(int), 1, 8),
                "Throttle": np.where(np.gradient(speed) >= 0, 100.0, 0.0),
                "Brake": np.gradient(speed) < 0,
                "DRS": np.where((speed > 290) & drs, 12, 0).astype(int),
            }
        )
        pos_times = np.arange(0.0, session_end, 0.22) + 0.007 * index
        if position_until is not None:
            pos_times = pos_times[pos_times <= position_until]
        travelled = np.interp(pos_times, car_times, np.cumsum(speed / 3.6 * 0.25))
        angle = 2 * np.pi * travelled / TRACK_LENGTH_M
        on_track = pos_times >= RACE_START_SECONDS - 60.0
        pos_data[number] = pd.DataFrame(
            {
                "Date": CLOCK_ZERO + pd.to_timedelta(np.rint(pos_times * 1000), unit="ms"),
                "SessionTime": pd.to_timedelta(np.rint(pos_times * 1000), unit="ms"),
                # F1 sends (0, 0) until it has a position for the car.
                "X": np.where(on_track, np.rint(TRACK_RADIUS * np.sin(angle)), 0.0),
                "Y": np.where(on_track, np.rint(TRACK_RADIUS * np.cos(angle)), 0.0),
                "Z": 0.0,
                "Status": "OnTrack",
            }
        )

    results = pd.DataFrame(
        {
            "DriverNumber": list(DRIVERS),
            "Abbreviation": [driver["code"] for driver in DRIVERS.values()],
            "BroadcastName": [driver["name"].upper() for driver in DRIVERS.values()],
            "FullName": [driver["name"] for driver in DRIVERS.values()],
            "TeamName": [driver["team"] for driver in DRIVERS.values()],
            "TeamColor": [driver["colour"] for driver in DRIVERS.values()],
            # Empty throughout 2026.
            "CountryCode": ["", "", ""],
            "Position": [1.0, 2.0, 3.0],
            "ClassifiedPosition": ["1", "2", "R"],
            "GridPosition": [2.0, 1.0, 3.0],
            "Time": [_duration(990.5), _duration(4.0), pd.NaT],
            "Status": ["Finished", "Finished", "Retired"],
            "Points": [25.0, 18.0, 0.0],
            "Laps": [12.0, 12.0, 9.0],
        },
        index=list(DRIVERS),
    )
    weather_times = np.arange(30.0, session_end, 60.0)
    return SimpleNamespace(
        laps=laps,
        results=results,
        car_data=car_data,
        pos_data=pos_data,
        weather_data=pd.DataFrame(
            {
                "Time": pd.to_timedelta(weather_times, unit="s"),
                "AirTemp": 21.0 + 0.01 * np.arange(len(weather_times)),
                "TrackTemp": 38.04,
                "Humidity": 40.0,
                "Rainfall": False,
                "WindSpeed": 2.5,
            }
        ),
        race_control_messages=pd.DataFrame(
            {
                "Time": [CLOCK_ZERO + pd.Timedelta(seconds=540), CLOCK_ZERO + pd.Timedelta(seconds=842.5)],
                "Category": ["Flag", "Other"],
                "Message": ["GREEN LIGHT - PIT EXIT OPEN", "INCIDENT NOTED"],
                "Status": [None, None],
                "Flag": ["GREEN", None],
                "Scope": ["Track", np.nan],
                "Sector": [np.nan, np.nan],
                "RacingNumber": [None, "3"],
                "Lap": [1, 3],
            }
        ),
        track_status=pd.DataFrame({"Time": [_duration(0)], "Status": ["1"]}),
        session_status=pd.DataFrame({"Status": ["Inactive", "Started", "Finished", "Finalised", "Ends"]}),
        total_laps=LAPS,
        session_info={"Key": IDENTITY.session_key, "Meeting": {"Key": IDENTITY.meeting_key}},
        t0_date=CLOCK_ZERO,
    )


def _duration(seconds: float) -> pd.Timedelta:
    return pd.Timedelta(milliseconds=round(seconds * 1000))
