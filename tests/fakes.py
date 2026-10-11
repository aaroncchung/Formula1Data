"""A stand-in for a loaded FastF1 session, small enough to build in a test.

It carries the attributes ``f1data`` reads and nothing else. Each test removes
or damages one feed and checks that the damage is noticed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from f1data.coverage import measure_coverage
from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES

LAP_SECONDS = 80.0
SAMPLE_INTERVAL = 0.25
RACE_START = 600.0

DRIVERS = {"1": "AAA", "2": "BBB", "3": "CCC"}

# The feeds FastF1 does not load, as they arrive for a session where driver 1
# stopped once on lap 5.
EXTRAS = {
    PIT_STOP_SERIES: (
        b'\xef\xbb\xbf01:12:03.942{"PitTimes":{"1":[{"Timestamp":"2026-06-28T13:18:16.017Z",'
        b'"PitStop":{"RacingNumber":"1","PitStopTime":"2.4","PitLaneTime":"21.369","Lap":"5"}}]}}\r\n'
    ),
    CIRCUIT_INFO: b'{"corners":[{"number":1,"letter":"","x":10.0,"y":20.0,"angle":90.0,"distance_m":350.0}],"rotation":0.0}\n',
}


def measure(session: SimpleNamespace, session_type: str = "R", extras: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Measure a fake session as a fetch would, with the extra feeds present unless told otherwise."""
    return measure_coverage(session, session_type, EXTRAS if extras is None else extras)


def make_session(laps_per_driver: int = 10, drivers: dict[str, str] | None = None) -> SimpleNamespace:
    drivers = drivers or DRIVERS
    lap_rows: list[dict[str, Any]] = []
    for number, code in drivers.items():
        for lap in range(1, laps_per_driver + 1):
            start = RACE_START + (lap - 1) * LAP_SECONDS
            lap_rows.append(
                {
                    "DriverNumber": number,
                    "Driver": code,
                    "LapNumber": float(lap),
                    "LapStartTime": pd.Timedelta(seconds=start),
                    "Time": pd.Timedelta(seconds=start + LAP_SECONDS),
                    "Compound": "MEDIUM",
                    "TyreLife": float(lap),
                    "Stint": 1.0,
                    "FastF1Generated": False,
                    "PitInTime": pd.Timedelta(seconds=start + LAP_SECONDS - 5)
                    if (number, lap) == ("1", 5)
                    else pd.NaT,
                }
            )

    session_end = RACE_START + laps_per_driver * LAP_SECONDS
    times = pd.to_timedelta(np.arange(0.0, session_end + 60.0, SAMPLE_INTERVAL), unit="s")
    # No two samples running are the same, as no two of a moving car are: a
    # feed that sends the sample before again is a fault the coverage counts.
    step = np.arange(len(times)) % 40
    car = pd.DataFrame(
        {
            "SessionTime": times,
            "Speed": 200.0 + step,
            "Throttle": 80.0,
            "Brake": False,
            "nGear": 6,
            "RPM": 11000.0 + 25.0 * step,
        }
    )
    position = pd.DataFrame({"SessionTime": times, "X": 1200.0 + 10.0 * step, "Y": -340.0 - 10.0 * step})

    results = pd.DataFrame(
        {
            "DriverNumber": list(drivers),
            "Abbreviation": list(drivers.values()),
            "BroadcastName": [f"{code[0]} {code}" for code in drivers.values()],
            "Laps": float(laps_per_driver),
        },
        index=list(drivers),
    )
    return SimpleNamespace(
        laps=pd.DataFrame(lap_rows),
        results=results,
        car_data={number: car.copy() for number in drivers},
        pos_data={number: position.copy() for number in drivers},
        weather_data=pd.DataFrame({"Time": [pd.Timedelta(seconds=0)], "AirTemp": [21.0]}),
        race_control_messages=pd.DataFrame({"Message": ["GREEN LIGHT - PIT EXIT OPEN"]}),
        track_status=pd.DataFrame({"Time": [pd.Timedelta(seconds=0)], "Status": ["1"]}),
        session_status=pd.DataFrame({"Status": ["Inactive", "Started", "Finished", "Finalised", "Ends"]}),
        total_laps=laps_per_driver,
        session_info={"Key": 11315, "Meeting": {"Key": 1288}},
    )


def thin_to_one_sample_per_lap(session: SimpleNamespace, feed: str) -> None:
    """Keep the first sample of each lap, as a feed cut down in transit would."""
    for number, telemetry in getattr(session, feed).items():
        seconds = telemetry["SessionTime"].dt.total_seconds()
        lap_index = np.floor((seconds - RACE_START) / LAP_SECONDS)
        getattr(session, feed)[number] = telemetry.groupby(lap_index).head(1).reset_index(drop=True)
