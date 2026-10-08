"""A build, with the archive's feeds and Jolpica stood in for.

``Builder.build`` restores a snapshot, has FastF1 load it, and hands the loaded
session to the artifact writer. Here a snapshot's feeds are a fake session
(``tests/fakes.py``), FastF1's calendar row makes the loaded session from it,
and the artifact writer keeps what it was given. Everything in between is the
real code: gathering, measuring, correcting a record, merging the result.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

import pandas as pd
import requests

from f1data import build as build_module
from f1data.archive import Snapshot, write_snapshot
from f1data.classification import Classification
from f1data.httplog import ForbiddenHostError
from f1data.store import MemoryStore
from tests.fakes import make_session
from tests.test_archive import ARCHIVE_PATH, fetched_session
from tests.test_build_inputs import AUSTRIA_RESULT, RACE_START, World
from tests.test_publish import AUSTRIA

FIRST_FETCH = RACE_START + timedelta(hours=5)


class Loaded:
    """A FastF1 session as a build loads one from the archive."""

    def __init__(self, feeds, row: "Row") -> None:
        self._archived = {
            name: value.copy() if isinstance(value, pd.DataFrame) else value
            for name, value in vars(feeds).items()
        }
        self._results = self._archived.pop("results")
        # FastF1 loads the session information whatever the row says.
        self._archived.pop("session_info", None)
        # As FastF1 has it from the calendar row the session was made from.
        self.f1_api_support = row.f1_api_support
        self.session_info = {
            "Key": AUSTRIA,
            "Name": "Race",
            "Path": ARCHIVE_PATH,
            "Meeting": {"Key": 1288, "Name": "Austrian Grand Prix"},
            # Local time and the offset from UTC, as F1 files them: 13:00 UTC.
            "StartDate": datetime(2026, 6, 28, 15, 0),
            "GmtOffset": timedelta(hours=2),
        }
        # FastF1 keeps the calendar row a session was made from. The artifact
        # writer reads nothing out of it; a test reads it to see which row a
        # build was made from.
        self.event = {"RoundNumber": row.round, "EventName": row.meeting_name}
        self.date = datetime(2026, 6, 28, 13, 0)
        self.name = "Race"
        self.refused: list[str] = []

    @property
    def results(self):
        return self._results

    def load(self, **kwargs) -> None:
        # FastF1 asks Jolpica for the result and for the first-lap times while
        # it loads, and carries on without them when it cannot.
        try:
            requests.Session().get("https://jolpica.invalid/ergast/f1/2026/8/results.json", timeout=5)
        except ForbiddenHostError as exc:
            self.refused.append(str(exc))
        # And it loads the feeds only for a session it believes F1's API
        # covers. Otherwise every one of them is left as if it had not arrived.
        feeds = self._archived if self.f1_api_support else _no_feeds(self._archived)
        self.__dict__.update(feeds)


def _no_feeds(archived: dict) -> dict:
    empty = {}
    for name, value in archived.items():
        if isinstance(value, pd.DataFrame):
            empty[name] = value.iloc[0:0]
        elif isinstance(value, dict):
            empty[name] = {}
        else:
            empty[name] = None
    return empty


class Row:
    """FastF1's calendar row for a meeting, as far as a build uses it."""

    def __init__(self, world: "Archive", entry) -> None:
        self._world = world
        self.round = entry.round
        self.meeting_name = entry.meeting_name
        self.f1_api_support = world.f1_api_support

    def get_session(self, name: str) -> Loaded:
        session = Loaded(self._world.feeds[self._world.restoring], self)
        self._world.loaded.append(session)
        return session


class Archive(World):
    """The calendar, Jolpica and the archive's feeds, for tests that run ``Builder.build``."""

    def __init__(self, monkeypatch, laps, first_lap_ms=None) -> None:
        super().__init__(monkeypatch)
        self.store = MemoryStore()
        self.laps = dict(laps)
        self.first_lap_ms = dict(first_lap_ms or {})
        self.row_fingerprint = "sha256:the-row-as-first-read"
        # What the calendar's rows say of F1's API covering their sessions.
        self.f1_api_support = True
        # Snapshot id to the session its archived feeds load as.
        self.feeds: dict[str, object] = {}
        self.restoring: str | None = None
        self.loaded: list[Loaded] = []
        # Every session handed to the artifact writer, in order, and the raw
        # car feed handed over with each.
        self.built: list[Loaded] = []
        self.car_feeds: list[bytes | None] = []
        monkeypatch.setattr(build_module, "fastf1_cache", self._cache)
        monkeypatch.setattr(build_module, "restore_snapshot", self._restore)
        monkeypatch.setattr(build_module, "build_artifacts", self._artifacts)

    def load_schedule(self, fastf1, year, fresh=False, backend=None):
        return [
            replace(entry, event=Row(self, entry), row_fingerprint=self.row_fingerprint)
            for entry in super().load_schedule(fastf1, year, fresh, backend)
        ]

    def fetch_classification(self, fastf1, year, round_number, session_type):
        self.classification_requests.append(round_number)
        rows = [
            {"number": int(number), "laps": laps, "position": place, "points": 0.0}
            for place, (number, laps) in enumerate(sorted(self.laps.items()), start=1)
        ]
        return Classification(
            rows=rows,
            fingerprint=f"sha256:{sorted(self.laps.items())}{sorted(self.first_lap_ms.items())}",
            frame=pd.DataFrame(rows),
            race_date=AUSTRIA_RESULT["date"],
            first_lap_ms=dict(self.first_lap_ms),
        )

    def snapshot(self, tmp_path, recorded=None, feeds=None, moment: datetime = FIRST_FETCH) -> Snapshot:
        """Archive a fetch whose record is the measurement of ``recorded`` and
        whose feeds, when a build restores them, load as ``feeds``."""
        written = write_snapshot(self.store, fetched_session(tmp_path, recorded), now=moment)
        self.feeds[written.snapshot_id] = feeds or recorded or make_session()
        return written

    @contextmanager
    def _cache(self, cache_dir):
        yield None

    def _restore(self, store, snapshot, cache_dir):
        self.restoring = snapshot.snapshot_id
        return cache_dir

    def _artifacts(self, session, identity, classification, extras, coverage, car_feed=None):
        """Stands in for ``f1data.artifacts.build_artifacts``, with its signature.

        The real one puts nothing from the calendar into a generation. This
        one writes down the round of the row the session was made from, so
        that a test can tell which row that was.
        """
        self.built.append(session)
        self.car_feeds.append(car_feed)
        return {"summary.json": f"round {session.event['RoundNumber']}".encode()}
