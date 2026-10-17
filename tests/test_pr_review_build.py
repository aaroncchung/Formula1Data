"""The cases a Claude review of pull request 11 found in building and publishing, 2026-10-17, at 5190b36.

An empty answer from Jolpica, after the retry window, had a session built
without its result: the order on track was published in place of the
official result, and the pointer still said complete, since the snapshots
kept the laps classified on the day they were fetched. On an old session's
quiet days the pointer with no result was then taken as settled. A session
published with a result now keeps it, and one published without a result is
partial for want of it and is asked about on every run.

The index was not derived, nor the standings published, when the calendar of
any one season would not load, as next year's will not on the first of
January. A pointer could name its own generation as the one before it. And
nothing held what a build publishes to the pipeline version: that test is in
tests/test_layout.py.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import timedelta

import pytest

from f1data import cli, layout
from f1data.archive import dump_json
from f1data.build import Builder
from f1data.classification import ClassificationMissing
from f1data.coverage import CLASSIFICATION_BAR
from f1data.policy import CLASSIFICATION_RECHECK_WINDOW
from f1data.publish import CalendarUnavailable, publish_index, publish_session, read_pointer
from f1data.store import DirectoryStore, MemoryStore
from tests import sample_bucket
from tests.building import Archive
from tests.fakes import make_session
from tests.test_build_inputs import a_quiet_day, a_recheck_day
from tests.test_fifth_review import EVERYONE, WINDOW_CLOSED
from tests.test_publish import AUSTRIA, Publisher, pointer_of


def jolpica_has_nothing(*args, **kwargs):
    raise ClassificationMissing("Jolpica has no classification for 2026 round 8 R")


def publish(world: Archive, moment):
    builder = Builder(world.store, None, now=lambda: moment)
    return publish_session(world.store, AUSTRIA, builder.gather, builder.build)


# --- 1: an empty answer from Jolpica --------------------------------------------


def test_an_empty_answer_about_a_session_published_with_its_result_leaves_the_result_published(
    tmp_path, monkeypatch
):
    """The finding. The snapshot recorded the laps classified at fetch time,
    so built with no result it met every bar."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path, make_session(), moment=WINDOW_CLOSED)
    later = WINDOW_CLOSED + timedelta(days=3)
    assert publish(world, later).action == "published"
    before = read_pointer(world.store, AUSTRIA)[0]
    assert before.classification_fingerprint is not None and before.complete

    monkeypatch.setattr("f1data.build.fetch_classification", jolpica_has_nothing)
    outcome = publish(world, later + timedelta(hours=6))

    assert outcome.action == "waiting"
    assert "published with a result, which is kept until Jolpica has one again" in outcome.reason
    assert read_pointer(world.store, AUSTRIA)[0] == before
    assert len(world.built) == 1


def test_on_an_old_sessions_recheck_day_an_empty_answer_changes_nothing_either(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path, make_session(), moment=WINDOW_CLOSED)
    assert publish(world, WINDOW_CLOSED + timedelta(days=3)).action == "published"
    before = read_pointer(world.store, AUSTRIA)[0]

    official = world.fetch_classification
    monkeypatch.setattr("f1data.build.fetch_classification", jolpica_has_nothing)
    recheck = a_recheck_day(WINDOW_CLOSED + timedelta(days=40))
    assert publish(world, recheck).action == "waiting"
    monkeypatch.setattr("f1data.build.fetch_classification", official)
    assert publish(world, a_quiet_day(recheck + timedelta(days=2))).action == "current"

    assert read_pointer(world.store, AUSTRIA)[0] == before


def test_a_session_that_never_had_a_result_is_published_as_partial_for_want_of_one(tmp_path, monkeypatch):
    """What the comment in the build always said. Every driver is short of
    the classification, whatever the snapshot recorded of it."""
    world = Archive(monkeypatch, EVERYONE)
    snapshot = world.snapshot(tmp_path, make_session(), moment=WINDOW_CLOSED - timedelta(days=2))
    assert snapshot.complete
    monkeypatch.setattr("f1data.build.fetch_classification", jolpica_has_nothing)

    outcome = publish(world, WINDOW_CLOSED)

    assert outcome.action == "published"
    pointer = read_pointer(world.store, AUSTRIA)[0]
    assert pointer.classification_fingerprint is None and not pointer.complete
    assert {(item["bar"], item["driver"]) for item in pointer.shortfalls} == {
        (CLASSIFICATION_BAR, code) for code in ("AAA", "BBB", "CCC")
    }
    # The record a pointer keeps is of the feeds, which have not changed.
    assert pointer.record == snapshot.record_fingerprint


def test_a_session_published_without_a_result_is_asked_about_on_its_quiet_days(tmp_path, monkeypatch):
    """Otherwise an old session published with no result would be taken as
    settled for twenty-eight days in every thirty."""
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path, make_session(), moment=WINDOW_CLOSED - timedelta(days=2))
    official = world.fetch_classification
    monkeypatch.setattr("f1data.build.fetch_classification", jolpica_has_nothing)
    assert publish(world, WINDOW_CLOSED).action == "published"
    asked = len(world.classification_requests)

    monkeypatch.setattr("f1data.build.fetch_classification", official)
    quiet = a_quiet_day(WINDOW_CLOSED + CLASSIFICATION_RECHECK_WINDOW + timedelta(days=5))
    outcome = publish(world, quiet)

    assert len(world.classification_requests) == asked + 1
    assert (outcome.action, outcome.reason) == ("published", "the classification changed")
    pointer = read_pointer(world.store, AUSTRIA)[0]
    assert pointer.classification_fingerprint is not None and pointer.complete
    # Once it has one, its quiet days are quiet again.
    assert publish(world, a_quiet_day(quiet + timedelta(days=1))).action == "current"
    assert len(world.classification_requests) == asked + 1


# --- 2: a season whose calendar will not load ---------------------------------------

NO_SCHEDULE = ValueError("Failed to load any schedule data.")


def calendars(*missing: int):
    """FastF1's schedule for the sample's season, and its error for any year in ``missing``."""

    def load(year, **_):
        if year in missing:
            raise NO_SCHEDULE
        return sample_bucket.season() if year == sample_bucket.IDENTITY.year else []

    return load


def test_next_years_calendar_not_being_out_leaves_it_out_of_the_index(caplog):
    """The finding. The workflow asks for this year's season, and on the first
    of January FastF1 has no calendar for it."""
    store = MemoryStore()
    sample_bucket.write_sample(store)
    before = store.get(layout.index_key()).data

    with caplog.at_level(logging.WARNING, logger="f1data.publish"):
        assert publish_index(store, calendars(2027), seasons=[2027]) == "current"

    assert store.get(layout.index_key()).data == before
    assert "The calendar of 2027 did not load, and nothing of 2027 is published" in caplog.text


def test_a_calendar_that_will_not_load_for_a_season_with_sessions_published_stops_the_index():
    store = MemoryStore()
    sample_bucket.write_sample(store)
    before = store.get(layout.index_key()).data

    with pytest.raises(CalendarUnavailable, match="The calendar of 2026 did not load, and sessions of 2026"):
        publish_index(store, calendars(2026), seasons=[2027])

    assert store.get(layout.index_key()).data == before


def build_args(store_path, season):
    return argparse.Namespace(
        store=str(store_path), session_key=None, shard=None, season=season, recheck=False
    )


@pytest.fixture
def jolpica_standings(monkeypatch):
    """Jolpica's standings, a point more for the winner than the sample has."""
    asked = []

    def fetch(fastf1, year):
        asked.append(year)
        if year != sample_bucket.IDENTITY.year:
            return None
        standings = sample_bucket.standings()
        standings["drivers"][0]["points"] += 1
        return standings

    monkeypatch.setattr("f1data.build.fetch_standings", fetch)
    return asked


def test_a_build_on_new_years_day_derives_the_index_and_publishes_the_standings(
    tmp_path, monkeypatch, capsys, jolpica_standings
):
    sample_bucket.write_sample(DirectoryStore(tmp_path))
    monkeypatch.setattr("f1data.build.load_schedule", lambda fastf1, year, **_: calendars(2027)(year))

    assert cli.run_build(build_args(tmp_path, [2027])) == 0

    out = capsys.readouterr().out
    assert f"index ({layout.index_key()}): current" in out
    assert f"standings 2026 ({layout.standings_key(2026)}): published" in out
    assert jolpica_standings == [2026, 2027]


def test_the_standings_are_published_when_the_index_cannot_be_derived_and_the_build_fails(
    tmp_path, monkeypatch, capsys, jolpica_standings
):
    store = DirectoryStore(tmp_path)
    sample_bucket.write_sample(store)
    before = store.get(layout.index_key()).data
    monkeypatch.setattr("f1data.build.load_schedule", lambda fastf1, year, **_: calendars(2026)(year))

    assert cli.run_build(build_args(tmp_path, [2026])) == 1

    out = capsys.readouterr().out
    assert (
        f"index ({layout.index_key()}): FAILED: CalendarUnavailable: The calendar of 2026 did not load" in out
    )
    assert f"standings 2026 ({layout.standings_key(2026)}): published" in out
    assert store.get(layout.index_key()).data == before


# --- 4: a pointer never names its own generation as the one before ------------------

OTHER_FILES = {"summary.json": b'{"meeting":"Austrian Grand Prix","laps":71}\n', "laps.json": b"[]\n"}


def test_a_rebuild_that_lands_on_the_published_generation_keeps_the_one_before():
    """The finding: an input moved and the files did not, so the build is the
    generation already published. A pruner that keeps a pointer's generation
    and the one before would have kept one generation of the two."""
    store = MemoryStore()
    first = Publisher(store).publish().generation
    second = Publisher(store, fingerprint="sha256:second", files=OTHER_FILES).publish().generation
    assert pointer_of(store).previous_generation == first

    outcome = Publisher(store, fingerprint="sha256:after-a-penalty", files=OTHER_FILES).publish()

    assert (outcome.action, outcome.reason, outcome.generation) == (
        "published",
        "the classification changed",
        second,
    )
    assert (pointer_of(store).generation, pointer_of(store).previous_generation) == (second, first)


def test_a_first_publication_built_again_to_the_same_files_has_none_before_it():
    store = MemoryStore()
    first = Publisher(store).publish().generation

    Publisher(store, fingerprint="sha256:after-a-penalty").publish()

    assert (pointer_of(store).generation, pointer_of(store).previous_generation) == (first, None)


def test_a_pointer_written_naming_itself_as_the_one_before_is_put_right():
    store = MemoryStore()
    first = Publisher(store).publish().generation
    payload = json.loads(store.get(layout.pointer_key(AUSTRIA)).data)
    store.put(layout.pointer_key(AUSTRIA), dump_json({**payload, "previous_generation": first}))

    Publisher(store, fingerprint="sha256:after-a-penalty").publish()

    assert pointer_of(store).previous_generation is None
