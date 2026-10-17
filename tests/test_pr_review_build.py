"""The cases a Claude review of pull request 11 found in building and publishing, 2026-10-17, at 5190b36.

An empty answer from Jolpica, after the retry window, had a session built
without its result: the order on track was published in place of the
official result, and the pointer still said complete, since the snapshots
kept the laps classified on the day they were fetched. On an old session's
quiet days the pointer with no result was then taken as settled. A session
published with a result now keeps it, and one published without a result is
partial for want of it and is asked about on every run.
"""

from __future__ import annotations

from datetime import timedelta

from f1data.build import Builder
from f1data.classification import ClassificationMissing
from f1data.coverage import CLASSIFICATION_BAR
from f1data.policy import CLASSIFICATION_RECHECK_WINDOW
from f1data.publish import publish_session, read_pointer
from tests.building import Archive
from tests.fakes import make_session
from tests.test_build_inputs import a_quiet_day, a_recheck_day
from tests.test_fifth_review import EVERYONE, WINDOW_CLOSED
from tests.test_publish import AUSTRIA


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
