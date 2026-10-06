"""What a build looks up before it builds: the calendar and the classification.

Both come from outside the archive, and both can be wrong for the session in
hand. These tests are the cases the first review of this code found
(GPT-6.1 Sol, 2026-10-06), and the rule each one belongs to.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import requests

from f1data import build as build_module
from f1data import layout
from f1data.archive import write_snapshot
from f1data.build import BuildError, Builder
from f1data.classification import Classification
from f1data.httplog import ForbiddenHostError
from f1data.policy import CLASSIFICATION_RECHECK_WINDOW
from f1data.publish import Inputs, publish_index, publish_session, read_pointer
from f1data.store import MemoryStore
from tests.test_archive import fetched_session
from tests.test_publish import AUSTRIA, Interposing, schedule_2026

RACE_START = datetime(2026, 6, 28, 13, 0, tzinfo=timezone.utc)
SOON_AFTER = RACE_START + timedelta(hours=6)

# Before the calendar changes Austria is round 8. Afterwards a race has been
# inserted ahead of it: Austria is round 9, and round 8 is a race a week earlier.
AUSTRIA_RESULT = {"date": date(2026, 6, 28), "fingerprint": "sha256:austria"}
OTHER_RESULT = {"date": date(2026, 6, 21), "fingerprint": "sha256:the-race-now-at-round-8"}


class World:
    """The calendar and Jolpica as they stand, which a test can change mid-run."""

    def __init__(self, monkeypatch):
        self.austria_round = 8
        self.results_by_round = {8: AUSTRIA_RESULT}
        self.schedule_reads: list[bool] = []
        self.classification_requests: list[int] = []
        monkeypatch.setattr(build_module, "load_schedule", self.load_schedule)
        monkeypatch.setattr(build_module, "fetch_classification", self.fetch_classification)

    def renumber(self):
        self.austria_round = 9
        self.results_by_round = {8: OTHER_RESULT, 9: AUSTRIA_RESULT}

    def load_schedule(self, fastf1, year, fresh=False):
        self.schedule_reads.append(fresh)
        return schedule_2026(austria_round=self.austria_round, italy_round=self.austria_round + 6)

    def fetch_classification(self, fastf1, year, round_number, session_type):
        self.classification_requests.append(round_number)
        result = self.results_by_round[round_number]
        rows = [{"number": number, "laps": 10} for number in ("1", "2", "3")]
        return Classification(rows=rows, fingerprint=result["fingerprint"], race_date=result["date"])


class StaleCalendar(World):
    """A publisher whose calendar will not refresh, whatever it asks for."""

    def load_schedule(self, fastf1, year, fresh=False):
        self.schedule_reads.append(fresh)
        return schedule_2026(austria_round=8, italy_round=14)


def archive(tmp_path, moment=RACE_START + timedelta(hours=5)) -> MemoryStore:
    store = MemoryStore()
    write_snapshot(store, fetched_session(tmp_path), now=moment)
    return store


def build_stub(inputs):
    return {"summary.json": inputs.classification_fingerprint.encode()}, None


# --- rule 2: decide again from current inputs, the calendar included ----------


def test_a_publisher_that_lost_a_write_reads_the_calendar_again(tmp_path, monkeypatch):
    """Publisher A read the calendar with Austria at round 8. The calendar is
    renumbered and B publishes from it. A loses its pointer write and decides
    again: from the calendar as it is now, not the copy it holds."""
    world = World(monkeypatch)
    store = Interposing(archive(tmp_path))
    a = Builder(store, fastf1=None, now=lambda: SOON_AFTER)
    b = Builder(store, fastf1=None, now=lambda: SOON_AFTER)

    def calendar_changes_and_b_publishes():
        world.renumber()
        assert publish_session(store, AUSTRIA, b.gather, build_stub).action == "published"

    store.before_put[layout.pointer_key(AUSTRIA)] = calendar_changes_and_b_publishes

    outcome = publish_session(store, AUSTRIA, a.gather, build_stub)

    assert outcome.action == "superseded"
    pointer, _ = read_pointer(store, AUSTRIA)
    assert pointer.classification_fingerprint == "sha256:austria"
    # A's second look asked for the calendar fresh, and so asked Jolpica for round 9.
    assert world.schedule_reads[-1] is True
    assert world.classification_requests[-1] == 9


def test_a_result_that_belongs_to_another_race_is_refused(tmp_path, monkeypatch):
    """The last line of defence: if the calendar this run holds is out of date
    and cannot be refreshed, the round it names is another race. Its result is
    never attached to this session's timing."""
    world = StaleCalendar(monkeypatch)
    world.renumber()
    store = archive(tmp_path)
    builder = Builder(store, fastf1=None, now=lambda: SOON_AFTER)

    with pytest.raises(BuildError, match="is a race on 2026-06-21, not session 11315"):
        publish_session(store, AUSTRIA, builder.gather, build_stub)
    assert read_pointer(store, AUSTRIA) == (None, None)


def test_a_result_with_no_date_cannot_be_tied_to_a_session(tmp_path, monkeypatch):
    world = World(monkeypatch)
    world.results_by_round = {8: {"date": None, "fingerprint": "sha256:undated"}}
    builder = Builder(archive(tmp_path), fastf1=None, now=lambda: SOON_AFTER)

    with pytest.raises(BuildError, match="carries no race date"):
        builder.gather(AUSTRIA)


def test_a_sprint_is_tied_to_the_date_of_its_sunday_race(tmp_path, monkeypatch):
    # Jolpica files a sprint's result under the race of the same weekend.
    world = World(monkeypatch)
    world.results_by_round = {8: {"date": date(2026, 6, 29), "fingerprint": "sha256:weekend"}}
    builder = Builder(archive(tmp_path), fastf1=None, now=lambda: SOON_AFTER)

    assert isinstance(builder.gather(AUSTRIA), Inputs)


def test_the_index_is_derived_from_a_fresh_calendar_after_a_lost_write(tmp_path, monkeypatch):
    world = World(monkeypatch)
    store = Interposing(archive(tmp_path))
    a = Builder(store, fastf1=None, now=lambda: SOON_AFTER)
    b = Builder(store, fastf1=None, now=lambda: SOON_AFTER)
    publish_session(store, AUSTRIA, a.gather, build_stub)
    assert a.schedule(2026)[1].round == 8

    def calendar_changes_and_b_publishes_the_index():
        world.renumber()
        assert publish_index(store, b.schedule) == "published"

    store.before_put[layout.index_key()] = calendar_changes_and_b_publishes_the_index

    publish_index(store, a.schedule)

    import json

    index = json.loads(store.get(layout.index_key()).data)
    rounds = [meeting["round"] for meeting in index["seasons"][0]["meetings"]]
    assert rounds == [9, 15]


# --- rule 4: nothing a build looks up comes from F1 ---------------------------


def test_looking_up_the_calendar_cannot_reach_f1(tmp_path, monkeypatch):
    """FastF1 falls back from its schedule file to F1's own site. A build that
    let it would be fetching from F1 on a runner F1 refuses."""
    attempts = []

    def schedule_that_falls_back_to_f1(fastf1, year, fresh=False):
        try:
            requests.Session().get("https://livetiming.formula1.com/static/2026/Index.json", timeout=5)
        except ForbiddenHostError as exc:
            attempts.append(str(exc))
            raise

    monkeypatch.setattr(build_module, "load_schedule", schedule_that_falls_back_to_f1)
    builder = Builder(archive(tmp_path), fastf1=None)

    with pytest.raises(ForbiddenHostError):
        builder.gather(AUSTRIA)
    assert attempts == ["This stage must not contact livetiming.formula1.com"]


def test_asking_for_the_classification_cannot_reach_f1(tmp_path, monkeypatch):
    World(monkeypatch)

    def classification_by_way_of_f1(fastf1, year, round_number, session_type):
        requests.Session().get("https://livetiming-mirror.fastf1.dev/static/2026/Index.json", timeout=5)

    monkeypatch.setattr(build_module, "fetch_classification", classification_by_way_of_f1)

    with pytest.raises(ForbiddenHostError):
        Builder(archive(tmp_path), fastf1=None, now=lambda: SOON_AFTER).gather(AUSTRIA)


# --- recent rounds are asked about on every run; old ones are left alone -------


def test_an_old_session_is_not_asked_about_on_every_run(tmp_path, monkeypatch):
    world = World(monkeypatch)
    store = archive(tmp_path)
    clock = [SOON_AFTER]
    builder = Builder(store, fastf1=None, now=lambda: clock[0])
    publish_session(store, AUSTRIA, builder.gather, build_stub)
    world.classification_requests.clear()

    clock[0] = RACE_START + CLASSIFICATION_RECHECK_WINDOW - timedelta(hours=1)
    assert publish_session(store, AUSTRIA, builder.gather, build_stub).action == "current"
    assert world.classification_requests == [8]

    clock[0] = RACE_START + CLASSIFICATION_RECHECK_WINDOW + timedelta(hours=1)
    world.classification_requests.clear()
    assert publish_session(store, AUSTRIA, builder.gather, build_stub).action == "current"
    assert world.classification_requests == []


def test_an_old_session_is_built_again_when_a_different_snapshot_would_be_picked(tmp_path, monkeypatch):
    world = World(monkeypatch)
    store = archive(tmp_path / "first")
    long_after = RACE_START + CLASSIFICATION_RECHECK_WINDOW + timedelta(days=60)
    builder = Builder(store, fastf1=None, now=lambda: long_after)
    first = publish_session(store, AUSTRIA, builder.gather, build_stub)
    write_snapshot(store, fetched_session(tmp_path / "second"), now=long_after - timedelta(days=1))
    world.classification_requests.clear()

    second = publish_session(store, AUSTRIA, builder.gather, build_stub)

    assert (first.action, second.action) == ("published", "published")
    assert second.reason == "a different snapshot is now selected"
    assert world.classification_requests == [8]


def test_an_old_session_is_built_again_by_a_newer_pipeline_version(tmp_path, monkeypatch):
    world = World(monkeypatch)
    store = archive(tmp_path)
    long_after = RACE_START + CLASSIFICATION_RECHECK_WINDOW + timedelta(days=60)
    builder = Builder(store, fastf1=None, now=lambda: long_after)
    publish_session(store, AUSTRIA, builder.gather, build_stub)
    monkeypatch.setattr(layout, "PIPELINE_VERSION", layout.PIPELINE_VERSION + 1)
    world.classification_requests.clear()

    outcome = publish_session(store, AUSTRIA, builder.gather, build_stub)

    assert outcome.action == "published"
    assert outcome.reason.startswith("pipeline version")
    assert world.classification_requests == [8]
