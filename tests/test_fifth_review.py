"""The cases the fifth review of this code found (GPT-6.1 Sol, 2026-10-06, at d864341).

Both came in with the fix before. Two answers from Jolpica were put together
without checking they were about one race; and the correction of a record was
trusted further than it had earned: it could be measured through a calendar
row that switches the feeds off, written over a correction nobody had read,
and never looked at again once a session was published.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

import pandas as pd
import pytest

from f1data import build as build_module
from f1data import layout
from f1data.archive import list_snapshots, write_remeasurement
from f1data.build import Builder
from f1data.classification import ClassificationUnavailable, fetch_classification, fetch_classified_laps
from f1data.policy import CLASSIFICATION_RECHECK_WINDOW, RETRY_WINDOW, SLOW_RETRY_INTERVAL
from f1data.publish import Hold, publish_session, read_pointer
from f1data.store import PreconditionFailed
from tests.building import FIRST_FETCH, Archive
from tests.fakes import make_session, measure
from tests.test_build_inputs import RACE_START, SOON_AFTER, a_quiet_day
from tests.test_classification import Jolpica as JolpicaClient
from tests.test_fourth_review import about_the_race_of, first_laps, without_positions_for_one_driver
from tests.test_publish import AUSTRIA, Interposing
from tests.test_second_review import planned

EVERYONE = {"1": 10, "2": 10, "3": 10}
WINDOW_CLOSED = FIRST_FETCH + RETRY_WINDOW


def result_of_the_fake_session() -> pd.DataFrame:
    """Jolpica's result for the three drivers of ``tests/fakes.py``."""
    return pd.DataFrame(
        {
            "number": [1, 2, 3],
            "driverId": ["aaa", "bbb", "ccc"],
            "driverCode": ["AAA", "BBB", "CCC"],
            "position": [1, 2, 3],
            "positionText": ["1", "2", "3"],
            "laps": [10, 10, 10],
            "points": [25.0, 18.0, 15.0],
        }
    )


def jolpica(result_day="2026-06-28", laps_day="2026-06-28", times=None) -> JolpicaClient:
    client = JolpicaClient([result_of_the_fake_session()], first_laps=[] if times is None else [times])
    client.description = about_the_race_of(result_day)
    client.lap_description = about_the_race_of(laps_day) if laps_day else None
    return client


def correction_key(snapshot) -> str:
    return f"{layout.snapshot_prefix(AUSTRIA, snapshot.snapshot_id)}{layout.REMEASUREMENT_NAME}"


def correction(store, snapshot) -> dict:
    return json.loads(store.get(correction_key(snapshot)).data)


# --- P0: two answers from Jolpica are used together only if they are of one race ---


def test_first_lap_times_of_another_race_are_not_joined_to_this_ones_result():
    """Asked by round, one after the other. Between the two Jolpica inserts a
    race, and round 8 is now a race a week earlier with most of the same
    drivers in it."""
    same_race = fetch_classification(jolpica(times=first_laps(aaa=91.5, bbb=92.25)), 2026, 8, "R")
    assert same_race.first_lap_ms == {"1": 91500, "2": 92250}

    with pytest.raises(ClassificationUnavailable, match="the result of one race and the first-lap times of another"):
        fetch_classification(jolpica(laps_day="2026-06-21", times=first_laps(aaa=88.0, bbb=89.0)), 2026, 8, "R")

    # Times that do not say which race they are of cannot be tied to one.
    with pytest.raises(ClassificationUnavailable):
        fetch_classification(jolpica(laps_day=None, times=first_laps(aaa=88.0)), 2026, 8, "R")

    # No times at all is still no times, whatever the answer says it is about.
    assert fetch_classification(jolpica(laps_day="2026-06-21"), 2026, 8, "R").first_lap_ms == {}


def test_a_session_waits_when_jolpicas_answers_are_of_two_races(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)
    # Jolpica itself this time, as far as ``fetch_classification`` can tell.
    monkeypatch.setattr(build_module, "fetch_classification", fetch_classification)
    answers = jolpica(laps_day="2026-06-21", times=first_laps(aaa=88.0, bbb=89.0))
    builder = Builder(world.store, fastf1=answers, now=lambda: SOON_AFTER)

    held = builder.gather(AUSTRIA)

    assert isinstance(held, Hold)
    assert "the result of one race and the first-lap times of another" in held.reason

    answers = jolpica(laps_day="2026-06-21", times=first_laps(aaa=88.0, bbb=89.0))
    builder = Builder(world.store, fastf1=answers, now=lambda: SOON_AFTER)
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)
    assert outcome.action == "waiting"
    assert read_pointer(world.store, AUSTRIA) == (None, None)
    assert world.built == []


def test_the_fetch_planner_takes_classified_laps_only_from_the_race_of_that_day():
    def laps(result_day: str, session_date: date, session_type: str = "R"):
        return fetch_classified_laps(jolpica(result_day=result_day), 2026, 8, session_type, session_date)

    assert laps("2026-06-28", date(2026, 6, 28)) == {"1": 10, "2": 10, "3": 10}
    # A sprint is filed under its Sunday race.
    assert laps("2026-06-28", date(2026, 6, 27), "S") == {"1": 10, "2": 10, "3": 10}
    with pytest.raises(ClassificationUnavailable, match="is not the race of 2026-06-28"):
        laps("2026-06-21", date(2026, 6, 28))
    undated = JolpicaClient([result_of_the_fake_session()])
    with pytest.raises(ClassificationUnavailable):
        fetch_classified_laps(undated, 2026, 8, "R", date(2026, 6, 28))


# --- P1: what a correction rests on, and how far it is trusted --------------------


def test_a_calendar_row_that_says_f1_does_not_cover_the_session_does_not_empty_the_archive(tmp_path, monkeypatch):
    """FastF1 loads no feed for a session whose row has the flag unset, and
    the identity check still passes. A build measured through such a row
    would record every feed in the snapshot as absent."""
    world = Archive(monkeypatch, EVERYONE)
    world.f1_api_support = False
    written = world.snapshot(tmp_path)
    builder = Builder(world.store, fastf1=None, now=lambda: SOON_AFTER)

    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert read_pointer(world.store, AUSTRIA)[0].complete is True
    assert world.store.get(correction_key(written)) is None
    (built,) = world.built
    assert built.f1_api_support is True and len(built.laps) == 30


def test_a_correction_is_not_written_over_one_that_was_not_read(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)
    store = world.store
    short = measure(without_positions_for_one_driver(10))
    (as_listed,) = list_snapshots(store)

    # Nobody had corrected it when this publisher listed it. Then someone does.
    write_remeasurement(store, as_listed, short, now=FIRST_FETCH + timedelta(hours=1))
    with pytest.raises(PreconditionFailed):
        write_remeasurement(store, as_listed, measure(make_session()), now=FIRST_FETCH + timedelta(hours=2))
    assert correction(store, as_listed)["measured_at"] == "2026-06-28T19:00:00Z"

    # Listed with that correction, and it is replaced by a third meanwhile.
    (with_the_first,) = list_snapshots(store)
    write_remeasurement(store, with_the_first, short, now=FIRST_FETCH + timedelta(hours=3))
    with pytest.raises(PreconditionFailed):
        write_remeasurement(store, with_the_first, measure(make_session()), now=FIRST_FETCH + timedelta(hours=4))
    assert correction(store, as_listed)["measured_at"] == "2026-06-28T21:00:00Z"


def test_a_build_beaten_to_a_correction_reads_it_before_deciding(tmp_path, monkeypatch):
    """Two builds find the same record wrong at the same time. The second to
    write does not write: it reads what the first wrote, and decides from that."""
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path, recorded=make_session(), feeds=without_positions_for_one_driver(10))
    store = Interposing(world.store)
    builder = Builder(store, fastf1=None, now=lambda: WINDOW_CLOSED)

    def another_build_corrects_it_first():
        (as_listed,) = list_snapshots(world.store)
        write_remeasurement(
            world.store, as_listed, measure(without_positions_for_one_driver(10)), now=RACE_START + timedelta(days=1)
        )

    store.before_put[correction_key(written)] = another_build_corrects_it_first

    outcome = publish_session(store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert read_pointer(store, AUSTRIA)[0].complete is False
    assert correction(world.store, written)["measured_at"] == "2026-06-29T13:00:00Z"


def test_a_newer_pipeline_versions_measurement_is_left_alone(tmp_path, monkeypatch):
    """A newer version has measured the snapshot and found it short. This one
    measures it whole. As with a pointer, the newer version's word stands."""
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path)
    (as_listed,) = list_snapshots(world.store)
    with monkeypatch.context() as newer:
        newer.setattr(layout, "PIPELINE_VERSION", layout.PIPELINE_VERSION + 1)
        write_remeasurement(world.store, as_listed, measure(without_positions_for_one_driver(10)))
    before = world.store.get(correction_key(written)).data
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)

    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "newer"
    assert f"was measured by pipeline version {layout.PIPELINE_VERSION + 1}" in outcome.reason
    assert world.store.get(correction_key(written)).data == before
    assert read_pointer(world.store, AUSTRIA) == (None, None)
    (listed,) = list_snapshots(world.store)
    with pytest.raises(ValueError, match="was measured by pipeline version"):
        write_remeasurement(world.store, listed, measure(make_session()))


def test_an_older_pipeline_versions_measurement_is_replaced(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path)
    (as_listed,) = list_snapshots(world.store)
    with monkeypatch.context() as older:
        older.setattr(layout, "PIPELINE_VERSION", layout.PIPELINE_VERSION - 1)
        write_remeasurement(world.store, as_listed, measure(without_positions_for_one_driver(10)))
    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED)

    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert read_pointer(world.store, AUSTRIA)[0].complete is True
    assert correction(world.store, written)["pipeline_version"] == layout.PIPELINE_VERSION


def test_a_record_corrected_after_publication_is_measured_again(tmp_path, monkeypatch):
    """Published whole, from a record that is right. Then a faulty build
    writes a correction that says the snapshot is short. The pointer still
    matches in every other way, and used to be left as current for good, with
    the fetch stage owing a fetch the archive did not need."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)
    store = world.store
    builder = Builder(store, fastf1=None, now=lambda: WINDOW_CLOSED)
    publish = lambda: publish_session(store, AUSTRIA, builder.gather, builder.build)
    assert publish().action == "published"
    (right,) = list_snapshots(store)
    assert read_pointer(store, AUSTRIA)[0].record == right.record_fingerprint
    assert publish().action == "current"

    write_remeasurement(store, right, measure(without_positions_for_one_driver(10)))
    (wrong,) = list_snapshots(store)
    assert not wrong.complete and wrong.record_fingerprint != right.record_fingerprint
    assert planned([wrong], FIRST_FETCH + SLOW_RETRY_INTERVAL) == [8]
    builds = len(world.loaded)

    outcome = publish()

    # Measured again, found whole, the correction corrected, nothing to publish.
    assert outcome.action == "current"
    assert len(world.loaded) == builds + 1
    (mended,) = list_snapshots(store)
    assert mended.complete and mended.record_fingerprint == right.record_fingerprint
    assert read_pointer(store, AUSTRIA)[0].complete is True
    assert planned([mended], FIRST_FETCH + SLOW_RETRY_INTERVAL) == []


def test_an_old_session_is_looked_at_again_when_its_record_is_corrected(tmp_path, monkeypatch):
    """Between the days its result is asked about, too."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)
    store = world.store
    first = Builder(store, fastf1=None, now=lambda: WINDOW_CLOSED)
    publish_session(store, AUSTRIA, first.gather, first.build)
    quiet = a_quiet_day(RACE_START + CLASSIFICATION_RECHECK_WINDOW + timedelta(days=60))
    builder = Builder(store, fastf1=None, now=lambda: quiet)
    world.classification_requests.clear()
    assert publish_session(store, AUSTRIA, builder.gather, builder.build).action == "current"
    assert world.classification_requests == []

    (right,) = list_snapshots(store)
    write_remeasurement(store, right, measure(without_positions_for_one_driver(10)))
    outcome = publish_session(store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "current"
    assert world.classification_requests != []
    assert list_snapshots(store)[0].complete


def test_the_pointer_keeps_the_record_whatever_the_result_of_the_day(tmp_path, monkeypatch):
    """The record's fingerprint is of the feeds. A result that changes, or a
    driver it adds, changes what the session is judged against and not this."""
    world = Archive(monkeypatch, EVERYONE)
    written = world.snapshot(tmp_path)
    judged = written.judged_against({"1": 11, "2": 10, "44": 10})

    assert judged.record_fingerprint == written.record_fingerprint
    assert written.record_fingerprint.startswith("sha256:") and len(written.record_fingerprint) == 71
    short = replace(written, coverage=measure(without_positions_for_one_driver(10)))
    assert short.record_fingerprint != written.record_fingerprint
