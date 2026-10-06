"""The cases the eighth review of this code found (GPT-6.1 Sol, 2026-10-06, at 042c5cb).

Asked to look at what is read back and what is parsed, it found that several
things were believed without being checked: a snapshot marker about the place
it was filed, a result about holding lap counts, a correction about who wrote
it, a fetch about when it was made, standings about being whole.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from f1data import build as build_module
from f1data import cli as cli_module
from f1data import layout
from f1data.archive import dump_json, list_snapshots, partial_publication_time, write_snapshot
from f1data.build import BuildError, Builder
from f1data.classification import ClassificationUnavailable, fetch_classification, fetch_classified_laps
from f1data.due import plan_fetches
from f1data.fetch import f1_is_answering
from f1data.policy import RETRY_INTERVAL, RETRY_WINDOW
from f1data.publish import Hold, Inputs, PointerError, publish_index, publish_session, read_pointer
from f1data.standings import StandingsError, fetch_standings, publish_standings
from f1data.store import MemoryStore
from tests.building import FIRST_FETCH, Archive
from tests.fakes import make_session
from tests.test_archive import fetched_session
from tests.test_build_inputs import SOON_AFTER
from tests.test_classification import Jolpica as JolpicaClient
from tests.test_classification import result_frame
from tests.test_fifth_review import WINDOW_CLOSED, correction, correction_key, jolpica
from tests.test_fourth_review import about_the_race_of, without_positions_for_one_driver
from tests.test_publish import AUSTRIA, ITALY, snapshot
from tests.test_second_review import ONE_RACE, fetched_at, planned
from tests.test_seventh_review import fetch_due
from tests.test_standings import CONSTRUCTORS, DRIVERS

EVERYONE = {"1": 10, "2": 10, "3": 10}


# --- 1: a marker is the snapshot its key says, or it is no snapshot ---------------


def test_a_marker_filed_under_another_session_is_not_that_sessions_snapshot(tmp_path):
    """Austria's marker, copied whole into Italy's part of the archive. Listed
    as Italy's it was built as Italy's, from Austria's feeds, and published
    under Italy's pointer."""
    store = MemoryStore()
    written = write_snapshot(store, fetched_session(tmp_path), now=FIRST_FETCH)
    marker = store.get(f"{layout.snapshot_prefix(AUSTRIA, written.snapshot_id)}{layout.SNAPSHOT_MARKER}")
    store.put(f"{layout.snapshot_prefix(ITALY, written.snapshot_id)}{layout.SNAPSHOT_MARKER}", marker.data)

    assert list_snapshots(store, ITALY) == []
    assert list_snapshots(store) == [written]

    outcome = publish_session(
        store,
        ITALY,
        lambda key, **_: Inputs(listed[0], "sha256:x") if (listed := list_snapshots(store, key)) else None,
        lambda inputs: ({"summary.json": b"{}\n"}, None),
    )
    assert outcome.action == "no_snapshot"
    assert read_pointer(store, ITALY) == (None, None)


def test_something_that_is_not_a_marker_does_not_stop_the_archive_being_read(tmp_path):
    """One stray object used to raise out of the listing, before either stage
    had started on anything."""
    store = MemoryStore()
    written = write_snapshot(store, fetched_session(tmp_path), now=FIRST_FETCH)
    store.put("archive/sessions/notes/snapshot.json", b"{}")
    store.put(f"archive/sessions/{AUSTRIA}/not-a-snapshot-id/snapshot.json", dump_json(written.to_json()))
    store.put(f"{layout.snapshot_prefix(AUSTRIA, '20260101T000000Z-bbbbbbbb')}snapshot.json", b"not json")
    # Its own marker, under another snapshot's name.
    store.put(
        f"{layout.snapshot_prefix(AUSTRIA, '20260102T000000Z-cccccccc')}snapshot.json", dump_json(written.to_json())
    )

    assert list_snapshots(store) == [written]
    assert list_snapshots(store, AUSTRIA) == [written]
    assert planned(list_snapshots(store), FIRST_FETCH + RETRY_INTERVAL) == []


def test_a_snapshot_is_never_published_under_another_sessions_pointer():
    store = MemoryStore()

    with pytest.raises(PointerError, match="is of session 11315, not session 11361"):
        publish_session(
            store,
            ITALY,
            lambda key, **_: Inputs(snapshot(AUSTRIA), "sha256:x"),
            lambda inputs: ({"summary.json": b"{}\n"}, None),
        )
    assert read_pointer(store, ITALY) == (None, None)


# --- 2: whether F1 answers is not asked of the season that failed -----------------


def test_f1_is_answering_if_any_season_that_should_exist_answers(monkeypatch):
    asked = []

    class Answer:
        def __init__(self, status):
            self.status_code = status

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

    def get_answer(url, **kwargs):
        asked.append(url)
        if "/2026/" in url:
            raise requests.ConnectionError("reset")
        return Answer(200 if "/2025/" in url else 404)

    monkeypatch.setattr(requests, "get", get_answer)

    assert f1_is_answering((2026, 2025)) is True
    assert [url.rsplit("/static/", 1)[1] for url in asked] == ["2026/Index.json", "2025/Index.json"]
    assert f1_is_answering((2017,)) is False
    assert f1_is_answering(()) is False


def test_a_season_f1_does_not_hold_does_not_stop_the_seasons_it_does(tmp_path, monkeypatch, capsys):
    """Two sessions of an old season fail, and that season has no index. The
    batch asks about this year and last, not about the season that failed."""
    asked = []

    def answering(years):
        asked.append(tuple(years))
        return True

    attempted, _, _ = fetch_due(tmp_path, monkeypatch, capsys, f1_answers=answering)

    this_year = datetime.now(timezone.utc).year
    assert attempted == [6, 7, 8]
    assert asked == [(this_year, this_year - 1)]


# --- 3: a session is found in the calendar by any of its fetches -------------------

MONDAY = "2026-06-29T14:00:00Z"


class Postponed(Archive):
    """The calendar after Austria's start was corrected to the Monday, more
    than twelve hours on."""

    def load_schedule(self, fastf1, year, fresh=False, backend=None):
        return [
            replace(entry, start_time_utc=MONDAY) if entry.round == self.austria_round and entry.session_type == "R" else entry
            for entry in super().load_schedule(fastf1, year, fresh, backend)
        ]

    def refetched(self, tmp_path, feeds=None, moment=FIRST_FETCH + RETRY_INTERVAL):
        """A fetch made since the correction: the same F1 session, with the new start time."""
        fetched = fetched_session(tmp_path, feeds)
        fetched = replace(fetched, identity=replace(fetched.identity, start_time_utc=MONDAY))
        written = write_snapshot(self.store, fetched, now=moment)
        self.feeds[written.snapshot_id] = feeds or make_session()
        return written


def test_a_session_whose_start_was_corrected_is_built_from_a_fetch_made_since(tmp_path, monkeypatch):
    """The first fetch recorded Sunday's start. Its identity finds no calendar
    entry any more, and it is the first snapshot listed: gathering used to
    stop there, whatever had been fetched since."""
    world = Postponed(monkeypatch, EVERYONE)
    world.snapshot(tmp_path / "sunday")
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)
    with pytest.raises(BuildError, match="No calendar entry for session 11315"):
        builder.gather(AUSTRIA)

    since = world.refetched(tmp_path / "monday")
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    pointer, _ = read_pointer(world.store, AUSTRIA)
    assert (pointer.snapshot_id, pointer.identity.start_time_utc) == (since.snapshot_id, MONDAY)


def test_an_older_fetch_is_published_as_the_session_the_calendar_now_has(tmp_path, monkeypatch):
    """The fetch made since the correction is the worse of the two, so the one
    from before is built. It is the same session, and is published with the
    start the calendar can place."""
    world = Postponed(monkeypatch, EVERYONE)
    before = world.snapshot(tmp_path / "sunday")
    world.refetched(tmp_path / "monday", feeds=without_positions_for_one_driver(10))
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)

    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    pointer, _ = read_pointer(world.store, AUSTRIA)
    assert (pointer.snapshot_id, pointer.complete) == (before.snapshot_id, True)
    assert pointer.identity.start_time_utc == MONDAY
    # And the index, which is derived from pointers and the calendar, has it.
    publish_index(world.store, builder.schedule)
    import json

    index = json.loads(world.store.get(layout.index_key()).data)
    race = next(
        session
        for meeting in index["seasons"][0]["meetings"]
        for session in meeting["sessions"]
        if session["type"] == "R" and meeting["round"] == 8
    )
    assert race["session_key"] == AUSTRIA and index["unscheduled"] == []


# --- 4: a result without lap counts is not the whole answer -----------------------


def test_a_result_with_no_lap_counts_is_not_a_classification():
    """Taken as one, it made every driver "not classified, so no laps to
    account for", and a session with a feed missing passed every bar."""
    without_laps = JolpicaClient([result_frame().drop(columns=["laps"])])
    without_laps.description = about_the_race_of("2026-06-28")
    with pytest.raises(ClassificationUnavailable, match="does not give every driver a number and a lap count"):
        fetch_classification(without_laps, 2026, 8, "R", sleep=lambda seconds: None)

    one_missing = result_frame().astype({"laps": "float64"})
    one_missing.loc[1, "laps"] = float("nan")
    with pytest.raises(ClassificationUnavailable):
        fetch_classification(JolpicaClient([one_missing]), 2026, 8, "R", sleep=lambda seconds: None)

    no_number = result_frame().astype({"number": "float64"})
    no_number.loc[0, "number"] = float("nan")
    lookup = JolpicaClient([no_number])
    lookup.description = about_the_race_of("2026-06-28")
    with pytest.raises(ClassificationUnavailable):
        fetch_classified_laps(lookup, 2026, 8, "R", date(2026, 6, 28), sleep=lambda seconds: None)


def test_a_session_waits_for_a_result_that_has_lap_counts(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path, recorded=without_positions_for_one_driver(10), feeds=without_positions_for_one_driver(10))
    monkeypatch.setattr(build_module, "fetch_classification", fetch_classification)
    answers = jolpica()
    answers._answers = [answers._answers[0].drop(columns=["laps"])]
    builder = Builder(world.store, fastf1=answers, now=lambda: WINDOW_CLOSED)

    held = builder.gather(AUSTRIA)

    assert isinstance(held, Hold) and "lap count" in held.reason


def test_a_result_that_is_only_its_first_page_is_not_used():
    partial = JolpicaClient([result_frame()])
    partial.description = about_the_race_of("2026-06-28")
    original = partial._answer

    def first_page_only(kind, season, round_number):
        answer = original(kind, season, round_number)
        answer.is_complete = False
        return answer

    partial._answer = first_page_only

    with pytest.raises(ClassificationUnavailable, match="only part of"):
        fetch_classification(partial, 2026, 8, "R", sleep=lambda seconds: None)


# --- 5: a correction that cannot be read has no authority either -------------------


def test_a_broken_correction_that_claims_a_newer_pipeline_version_is_replaced(tmp_path, monkeypatch):
    """Its claim used to be read before the rest was checked, and kept when
    the rest was thrown away: a record that needed correcting could then never
    be corrected by this version."""
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path, recorded=make_session(), feeds=without_positions_for_one_driver(10))
    claim = {
        "schema_version": 1,
        "snapshot_id": written.snapshot_id,
        "pipeline_version": layout.PIPELINE_VERSION + 1,
    }
    for coverage in (None, "none", {"measurement_version": 2}, {"measurement_version": 2, "feeds": [], "drivers": {}}):
        world.store.put(correction_key(written), dump_json({**claim, "coverage": coverage}))
        (listed,) = list_snapshots(world.store)
        assert (listed.corrected_by, listed.complete) == (None, True), coverage
        assert listed.correction_etag is not None

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert read_pointer(world.store, AUSTRIA)[0].complete is False
    assert correction(world.store, written)["pipeline_version"] == layout.PIPELINE_VERSION


def test_a_whole_correction_by_a_newer_measurement_keeps_its_authority(tmp_path, monkeypatch):
    """This version cannot use the figures, and still may not replace them."""
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path)
    newer = {
        "schema_version": 1,
        "snapshot_id": written.snapshot_id,
        "pipeline_version": layout.PIPELINE_VERSION + 1,
        "coverage": {**written.coverage, "measurement_version": written.coverage["measurement_version"] + 1},
    }
    world.store.put(correction_key(written), dump_json(newer))

    (listed,) = list_snapshots(world.store)

    assert listed.corrected_by == layout.PIPELINE_VERSION + 1
    assert listed.coverage == written.coverage


# --- 6: a fetch stamped in the future counts as made now --------------------------


def test_a_fetch_stamped_by_a_fast_clock_does_not_put_off_the_retries():
    """One machine's clock is two weeks ahead when it archives a short
    session. Every other machine used to wait two weeks to fetch it again."""
    now = FIRST_FETCH
    damaged = make_session()
    del damaged.pos_data["1"]
    stamped_ahead = snapshot(snapshot_id=fetched_at(now + timedelta(days=14)), session=damaged)

    # Nothing says when it was fetched, so it is fetched again at once.
    assert planned([stamped_ahead], now + timedelta(minutes=5)) == [8]
    assert partial_publication_time([stamped_ahead], now=now) == now + RETRY_WINDOW
    # That fetch is stamped by a clock that is right, and the clocks run from it.
    again = snapshot(snapshot_id=fetched_at(now + timedelta(hours=1)), session=damaged)
    assert planned([stamped_ahead, again], now + timedelta(hours=2)) == []
    assert planned([stamped_ahead, again], now + timedelta(hours=1) + RETRY_INTERVAL) == [8]
    assert partial_publication_time([stamped_ahead, again], now=now + timedelta(hours=2)) == (
        now + timedelta(hours=1) + RETRY_WINDOW
    )
    # A stamp a few minutes ahead is two clocks disagreeing, and is taken as it is.
    slightly = snapshot(snapshot_id=fetched_at(now + timedelta(hours=1)), session=damaged)
    assert planned([slightly], now + timedelta(minutes=30)) == []
    # With no clock to compare with, the stamp is all there is.
    assert partial_publication_time([stamped_ahead]) == now + timedelta(days=14) + RETRY_WINDOW


# --- 7 and 8: standings that are not whole are not "no standings yet" --------------


class Standings:
    """Stands in for ``fastf1``: Jolpica's two standings tables."""

    def __init__(self, drivers=DRIVERS, constructors=CONSTRUCTORS, description="round", complete=True):
        outer = self
        self.limits: list[int | None] = []

        def answer(frame):
            described = pd.DataFrame([{"season": 2026, description: 16}])
            return SimpleNamespace(content=[frame], description=described, is_complete=complete)

        class Client:
            def __init__(self, **kwargs):
                pass

            def get_driver_standings(self, season, limit=None):
                outer.limits.append(limit)
                return answer(drivers)

            def get_constructor_standings(self, season, limit=None):
                outer.limits.append(limit)
                return answer(constructors)

        @contextmanager
        def disabled():
            yield

        self.ergast = SimpleNamespace(Ergast=Client)
        self.Cache = SimpleNamespace(disabled=disabled)


def test_standings_are_asked_for_whole_and_a_first_page_is_refused():
    whole = Standings()

    assert fetch_standings(whole, 2026)["rounds"] == {"drivers": 16, "constructors": 16}
    assert whole.limits == [100, 100]
    with pytest.raises(StandingsError, match="only part of the standings"):
        fetch_standings(Standings(complete=False), 2026, sleep=lambda seconds: None)


def test_standings_that_cannot_be_published_are_an_error_and_not_an_absence():
    """Reported as "unavailable", which is what a season that has not started
    gets, the run went green with nothing written."""
    with pytest.raises(StandingsError, match="which round"):
        fetch_standings(Standings(description="rnd"), 2026, sleep=lambda seconds: None)
    pointless = DRIVERS.copy()
    pointless.loc[1, "points"] = float("nan")
    with pytest.raises(StandingsError, match="no position or no points"):
        fetch_standings(Standings(drivers=pointless), 2026, sleep=lambda seconds: None)

    # A season that has not started is still an absence.
    assert fetch_standings(Standings(drivers=DRIVERS.iloc[0:0]), 2026) is None


def test_a_stored_copy_that_is_not_standings_is_replaced():
    store = MemoryStore()
    store.put(layout.standings_key(2026), b"not standings")
    fetched = fetch_standings(Standings(), 2026)

    assert publish_standings(store, 2026, lambda year: fetched) == "published"
    assert publish_standings(store, 2026, lambda year: fetched) == "current"
