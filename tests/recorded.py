"""Recorded sessions from a source archive, loaded with no network at all.

For the tests that need real data (tests/test_recorded_race.py). They run when
``F1DATA_TEST_ARCHIVE`` names a store that holds the 2026 archive, a directory
or ``r2``, and are skipped otherwise.

A build gathers two things from outside the archive, the calendar row and
Jolpica's result with its first-lap times, and is then made with the network
refused. Here both are stood in for: the calendar row is made from what the
snapshot recorded of the session, and the Austrian race's result is a fixture
(``tests/fixtures/classification-11315.json``). With those, ``Builder.build``
itself runs on the archive and reads nothing else.
"""

from __future__ import annotations

import json
import os
import pickle
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from f1data.archive import Snapshot, list_snapshots, read_extras, restore_snapshot, select_snapshot
from f1data.build import BuildContext, Builder
from f1data.classification import Classification, fingerprint
from f1data.config import open_store
from f1data.extras import PIT_STOP_SERIES
from f1data.fetch import fastf1_cache
from f1data.httplog import HttpRecorder
from f1data.publish import Inputs
from f1data.schedule import ScheduledSession
from f1data.store import ObjectStore

ARCHIVE_VARIABLE = "F1DATA_TEST_ARCHIVE"
FIXTURES = Path(__file__).parent / "fixtures"

# The eleven feeds FastF1 requests when it loads a session, by the bar that
# answers for each (f1data/coverage.py), and the file FastF1 caches each in.
FEED_FILES = {
    "session_info": "session_info.ff1pkl",
    "driver_list": "driver_info.ff1pkl",
    "timing_data": "_extended_timing_data.ff1pkl",
    "tyre_data": "timing_app_data.ff1pkl",
    "track_status": "track_status_data.ff1pkl",
    "lap_count": "lap_count.ff1pkl",
    "session_status": "session_status_data.ff1pkl",
    "weather": "weather_data.ff1pkl",
    "race_control": "race_control_messages.ff1pkl",
    "car_data": "car_data.ff1pkl",
    "position": "position_data.ff1pkl",
}
# The feeds that carry something for each driver. The rest describe the session.
PER_DRIVER_FEEDS = ("driver_list", "timing_data", "tyre_data", "car_data", "position")


def archive_store() -> ObjectStore:
    spec = os.environ.get(ARCHIVE_VARIABLE)
    if not spec:
        pytest.skip(f"set {ARCHIVE_VARIABLE} to a store holding the 2026 archive (a directory, or r2)")
    return open_store(spec)


def restore(store: ObjectStore, session_key: int, cache_dir: Path) -> tuple[Snapshot, dict[str, bytes]]:
    """Unpack the snapshot a build would pick. Skips when the archive does not hold the session."""
    snapshot = select_snapshot(list_snapshots(store, session_key))
    if snapshot is None:
        pytest.skip(f"the archive holds no snapshot of session {session_key}")
    restore_snapshot(store, snapshot, cache_dir)
    return snapshot, read_extras(store, snapshot)


def calendar_row(snapshot: Snapshot) -> Any:
    """FastF1's calendar row for the snapshot's meeting, made from what the snapshot knows of it."""
    from fastf1.events import Event

    identity = snapshot.identity
    start = pd.Timestamp(identity.start_time_utc).tz_localize(None)
    return Event(
        {
            "RoundNumber": identity.round_at_fetch or 0,
            "Country": identity.country,
            "Location": identity.location,
            "OfficialEventName": identity.meeting_official_name,
            "EventDate": start.normalize(),
            "EventName": identity.meeting_name,
            "EventFormat": "conventional",
            "Session1": None,
            "Session2": None,
            "Session3": None,
            "Session4": None,
            "Session5": identity.session_name,
            "Session5Date": pd.NaT,
            "Session5DateUtc": start,
            "F1ApiSupport": True,
        },
        year=identity.year,
    )


def load_offline(snapshot: Snapshot, cache_dir: Path) -> Any:
    """The snapshot's session as FastF1 loads it from ``cache_dir``, with every host refused."""
    with fastf1_cache(cache_dir), HttpRecorder(forbid_all=True):
        session = calendar_row(snapshot).get_session(snapshot.identity.session_name)
        session.api_path = f"/static/{snapshot.identity.archive_path}"
        session.load(laps=True, telemetry=True, weather=True, messages=True)
    return session


def build_offline(store: ObjectStore, snapshot: Snapshot, classification: Classification | None) -> dict[str, bytes]:
    """``Builder.build`` on an archived snapshot, given what a run would have gathered for it."""
    identity = snapshot.identity
    scheduled = ScheduledSession(
        year=identity.year,
        round=identity.round_at_fetch or 0,
        meeting_name=identity.meeting_name,
        meeting_official_name=identity.meeting_official_name,
        country=identity.country,
        location=identity.location,
        meeting_date=identity.start_time_utc[:10],
        meeting_format="conventional",
        session_type=identity.session_type,
        session_name=identity.session_name,
        start_time_utc=identity.start_time_utc,
        event=calendar_row(snapshot),
    )
    # As gather does: the snapshot's record is judged against today's result.
    judged = snapshot.judged_against(classification.laps_by_number) if classification else snapshot
    inputs = Inputs(
        snapshot=judged,
        classification_fingerprint=classification.fingerprint if classification else None,
        context=BuildContext(scheduled=scheduled, classification=classification),
    )
    files, built_from = Builder(store, fastf1=None).build(inputs)
    assert built_from is judged
    return files


def without(base: Path, snapshot: Snapshot, target: Path, bar: str, driver_number: str | None = None) -> Path:
    """A copy of the cache at ``base`` with one feed removed, whole or for one driver."""
    feeds = Path(snapshot.identity.archive_path)
    removed = FEED_FILES[bar]
    (target / feeds).mkdir(parents=True)
    for path in sorted((base / feeds).glob("*.ff1pkl")):
        if path.name != removed:
            _link(path, target / feeds / path.name)
    if driver_number is not None:
        with (base / feeds / removed).open("rb") as handle:
            cached = pickle.load(handle)
        cached["data"] = _without_driver(cached["data"], driver_number)
        with (target / feeds / removed).open("wb") as handle:
            pickle.dump(cached, handle)
    return target


def without_pit_stops_of(extras: dict[str, bytes], driver_number: str) -> dict[str, bytes]:
    """The extras with one driver's lines taken out of F1's pit-stop feed."""
    kept = [
        line
        for line in extras[PIT_STOP_SERIES].splitlines(keepends=True)
        if f'"PitTimes":{{"{driver_number}":'.encode() not in line
    ]
    return {**extras, PIT_STOP_SERIES: b"".join(kept)}


def recorded_classification(session_key: int) -> Classification:
    """Jolpica's result for a session, with its first-lap times, as they stood when the fixture was recorded."""
    recorded = json.loads((FIXTURES / f"classification-{session_key}.json").read_text(encoding="utf-8"))
    rows, first_lap_ms = recorded["rows"], recorded["first_lap_ms"]
    frame = pd.DataFrame(rows)
    frame["totalRaceTime"] = pd.to_timedelta(frame["totalRaceTime"], unit="ms")
    return Classification(
        rows=rows, fingerprint=fingerprint(rows, first_lap_ms), frame=frame, first_lap_ms=first_lap_ms
    )


def classified_laps(snapshot: Snapshot) -> dict[str, int]:
    """Driver number to classified laps, as the snapshot recorded them when it was fetched."""
    return {
        str(driver["number"]): int(driver["classified_laps"])
        for driver in snapshot.coverage["drivers"].values()
        if driver.get("classified_laps") is not None
    }


def _without_driver(data: Any, number: str) -> Any:
    if isinstance(data, dict):
        return {key: value for key, value in data.items() if str(key) != number}
    if isinstance(data, tuple):
        return tuple(_without_driver(item, number) for item in data)
    if isinstance(data, pd.DataFrame) and "Driver" in data.columns:
        return data[data["Driver"].astype(str) != number].reset_index(drop=True)
    return data


def _link(source: Path, target: Path) -> None:
    # FastF1 only reads these, so the copies can share their bytes.
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)
