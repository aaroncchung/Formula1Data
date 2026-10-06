"""What the fetch stage asks F1 for, and when a short session stops waiting.

docs/architecture-review-findings.md, section 6, rules 3 and 6: fetching is
skipped only for sessions the archive holds in full, a short one is fetched
again until a retry window closes, and only then is it published as partial.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from f1data import build as build_module
from f1data.archive import write_snapshot
from f1data.build import Builder
from f1data.classification import Classification, ClassificationUnavailable
from f1data.coverage import evaluate_coverage
from f1data.due import plan_fetches
from f1data.policy import RETRY_INTERVAL, RETRY_WINDOW, SLOW_RETRY_INTERVAL
from f1data.publish import Hold, Inputs, publish_session, read_pointer
from f1data.store import MemoryStore
from f1data.extras import CIRCUIT_INFO
from tests.fakes import EXTRAS, make_session, measure
from tests.test_archive import fetched_session
from tests.test_publish import AUSTRIA, ITALY, schedule_2026, snapshot

RACE_START = datetime(2026, 6, 28, 13, 0, tzinfo=timezone.utc)
LONG_AFTER = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)


def planned(schedule, snapshots, now, **kwargs):
    return [(plan.session.round, plan.session.session_type) for plan in plan_fetches(schedule, snapshots, now, **kwargs)]


def without_position():
    session = make_session()
    del session.pos_data["1"]
    return session


def before_the_classification():
    session = make_session()
    session.results["Laps"] = float("nan")
    return session


def fetched_at(moment: datetime) -> str:
    return f"{moment.strftime('%Y%m%dT%H%M%SZ')}-aaaaaaaa"


# --- which sessions are due ---------------------------------------------------


def test_a_finished_session_in_scope_that_was_never_fetched_is_due():
    # Qualifying is on the calendar too, and is out of scope (decision 5).
    assert planned(schedule_2026(), [], LONG_AFTER) == [(8, "R"), (14, "R")]


def test_a_session_is_not_asked_for_until_its_feeds_can_be_in_the_archive():
    assert planned(schedule_2026(), [], RACE_START + timedelta(hours=3)) == []
    assert planned(schedule_2026(), [], RACE_START + timedelta(hours=4)) == [(8, "R")]


def test_a_session_the_archive_holds_in_full_is_never_fetched_again():
    assert planned(schedule_2026(), [snapshot()], LONG_AFTER) == [(14, "R")]


def test_a_session_is_recognised_after_the_calendar_is_renumbered():
    """AR-20: the archive holds the race that is now round 9, not "round 8"."""
    renumbered = schedule_2026(austria_round=9, italy_round=15)

    assert planned(renumbered, [snapshot()], LONG_AFTER) == [(15, "R")]


def test_a_short_session_is_fetched_again_at_intervals_until_the_window_closes():
    first_fetch = RACE_START + timedelta(hours=5)
    short = snapshot(snapshot_id=fetched_at(first_fetch), session=without_position())
    schedule = [entry for entry in schedule_2026() if entry.round == 8]

    assert planned(schedule, [short], first_fetch + timedelta(hours=1)) == []
    plans = plan_fetches(schedule, [short], first_fetch + RETRY_INTERVAL)
    assert [plan.reason for plan in plans] == ["best of 1 snapshot(s) is short on position"]
    assert planned(schedule, [short], first_fetch + RETRY_WINDOW) == []


def test_the_interval_runs_from_the_latest_fetch_and_the_window_from_the_first():
    first_fetch = RACE_START + timedelta(hours=5)
    second_fetch = first_fetch + RETRY_INTERVAL
    snapshots = [
        snapshot(snapshot_id=fetched_at(first_fetch), session=without_position()),
        snapshot(snapshot_id=fetched_at(second_fetch), session=without_position()),
    ]
    schedule = [entry for entry in schedule_2026() if entry.round == 8]

    assert planned(schedule, snapshots, second_fetch + timedelta(hours=1)) == []
    assert planned(schedule, snapshots, second_fetch + RETRY_INTERVAL) == [(8, "R")]
    assert planned(schedule, snapshots, first_fetch + RETRY_WINDOW) == []


def test_a_retry_that_met_every_bar_ends_the_retries():
    first_fetch = RACE_START + timedelta(hours=5)
    snapshots = [
        snapshot(snapshot_id=fetched_at(first_fetch), session=without_position()),
        snapshot(snapshot_id=fetched_at(first_fetch + RETRY_INTERVAL)),
    ]

    assert planned(schedule_2026(), snapshots, first_fetch + 3 * RETRY_INTERVAL) == []


def test_a_snapshot_waiting_only_for_the_classification_is_not_fetched_again():
    """Jolpica being hours behind is no reason to ask F1 a second time."""
    first_fetch = RACE_START + timedelta(hours=5)
    pending = snapshot(snapshot_id=fetched_at(first_fetch), session=before_the_classification())
    schedule = [entry for entry in schedule_2026() if entry.round == 8]
    assert {shortfall.bar for shortfall in pending.shortfalls()} == {"classification"}

    assert planned(schedule, [pending], first_fetch + RETRY_INTERVAL) == []


def test_timing_cut_short_before_the_classification_existed_is_caught_once_it_does():
    """Fetched before Jolpica had the result, with one lap per driver: nothing in
    the snapshot says a lap is missing until it is judged against the result."""
    first_fetch = RACE_START + timedelta(hours=5)
    cut_short = make_session(laps_per_driver=50)
    cut_short.laps = cut_short.laps[cut_short.laps["LapNumber"] <= 1]
    cut_short.results["Laps"] = float("nan")
    pending = snapshot(snapshot_id=fetched_at(first_fetch), session=cut_short)
    schedule = [entry for entry in schedule_2026() if entry.round == 8]
    later = first_fetch + RETRY_INTERVAL

    assert planned(schedule, [pending], later) == []
    assert planned(schedule, [pending], later, classified_laps=lambda session: {"1": 50, "2": 50, "3": 50}) == [
        (8, "R")
    ]


def test_a_snapshot_measured_before_a_feed_was_added_is_fetched_again_once():
    """A new bar is a new question, which a fetch from long ago never asked."""
    long_ago = RACE_START + timedelta(hours=5)
    old = snapshot(snapshot_id=fetched_at(long_ago))
    old.coverage["measurement_version"] = 1
    del old.coverage["feeds"]["circuit_info"]
    schedule = [entry for entry in schedule_2026() if entry.round == 8]

    plans = plan_fetches(schedule, [old], LONG_AFTER)

    assert [plan.reason for plan in plans] == ["fetched before the measured feeds changed"]

    # The fetch that looked for the new feed starts a retry window of its own.
    still_short = snapshot(snapshot_id=fetched_at(LONG_AFTER), session=without_position())
    assert planned(schedule, [old, still_short], LONG_AFTER + timedelta(hours=1)) == []
    assert planned(schedule, [old, still_short], LONG_AFTER + RETRY_INTERVAL) == [(8, "R")]
    assert planned(schedule, [old, still_short], LONG_AFTER + RETRY_WINDOW) == []


# --- judging against today's classification ----------------------------------


def test_a_snapshot_is_complete_once_the_classification_it_lacked_arrives():
    pending = snapshot(session=before_the_classification())
    assert not pending.complete

    judged = pending.judged_against({"1": 10, "2": 10, "3": 10})

    assert judged.complete
    # The stored snapshot is what was fetched; judging does not rewrite it.
    assert not pending.complete


def test_a_classified_driver_the_fetch_never_saw_is_a_shortfall():
    judged = snapshot().judged_against({"1": 10, "2": 10, "3": 10, "4": 10})

    bars = {(shortfall.bar, shortfall.driver) for shortfall in judged.shortfalls()}

    assert ("timing_data", "#4") in bars and ("driver_list", "#4") in bars


def test_feeds_are_still_judged_while_the_classification_is_missing():
    session = before_the_classification()
    del session.car_data["2"]

    bars = {(item.bar, item.driver) for item in evaluate_coverage(measure(session))}

    assert ("car_data", "BBB") in bars
    assert ("classification", "BBB") in bars


# --- when a short session is published ----------------------------------------


class Jolpica:
    """Stands in for the calendar and the classification a build looks up."""

    def __init__(self, monkeypatch, laps=None, available=True):
        self.laps = laps or {"1": 10, "2": 10, "3": 10}
        self.available = available
        monkeypatch.setattr(build_module, "load_schedule", lambda fastf1, year, fresh=False: schedule_2026())
        monkeypatch.setattr(build_module, "fetch_classification", self.fetch)

    def fetch(self, fastf1, year, round_number, session_type):
        if not self.available:
            raise ClassificationUnavailable(f"Jolpica has no classification for {year} round {round_number}")
        rows = [{"number": number, "laps": laps} for number, laps in sorted(self.laps.items())]
        return Classification(rows=rows, fingerprint="sha256:result", race_date=RACE_START.date())


def archived(tmp_path, moment: datetime, session=None) -> MemoryStore:
    store = MemoryStore()
    write_snapshot(store, fetched_session(tmp_path, session), now=moment)
    return store


def test_a_short_session_waits_for_a_better_fetch_then_is_published_as_partial(tmp_path, monkeypatch):
    Jolpica(monkeypatch)
    first_fetch = RACE_START + timedelta(hours=5)
    store = archived(tmp_path, first_fetch, without_position())
    clock = [first_fetch + timedelta(hours=1)]
    builder = Builder(store, fastf1=None, now=lambda: clock[0])
    build = lambda inputs: ({"summary.json": b"{}\n"}, None)

    waiting = publish_session(store, AUSTRIA, builder.gather, build)

    assert waiting.action == "waiting"
    assert waiting.reason.startswith("short on position; to be fetched again")
    assert read_pointer(store, AUSTRIA) == (None, None)

    clock[0] = first_fetch + RETRY_WINDOW
    published = publish_session(store, AUSTRIA, builder.gather, build)

    assert published.action == "published"
    pointer, _ = read_pointer(store, AUSTRIA)
    assert pointer.complete is False
    assert [item["bar"] for item in pointer.shortfalls] == ["position"]


def test_a_complete_session_is_published_at_once(tmp_path, monkeypatch):
    Jolpica(monkeypatch)
    store = archived(tmp_path, RACE_START + timedelta(hours=5))
    builder = Builder(store, fastf1=None, now=lambda: RACE_START + timedelta(hours=5, minutes=1))

    outcome = publish_session(store, AUSTRIA, builder.gather, lambda inputs: ({"summary.json": b"{}\n"}, None))

    assert outcome.action == "published"


def test_a_race_without_a_classification_yet_waits_and_is_not_a_failure(tmp_path, monkeypatch):
    Jolpica(monkeypatch, available=False)
    store = archived(tmp_path, RACE_START + timedelta(hours=5), before_the_classification())
    builder = Builder(store, fastf1=None, now=lambda: LONG_AFTER)

    outcome = publish_session(store, AUSTRIA, builder.gather, lambda inputs: ({}, None))

    assert outcome.action == "waiting"
    assert "no classification" in outcome.reason
    assert read_pointer(store, AUSTRIA) == (None, None)


def test_a_snapshot_fetched_before_the_classification_is_built_once_it_arrives(tmp_path, monkeypatch):
    Jolpica(monkeypatch)
    store = archived(tmp_path, RACE_START + timedelta(hours=5), before_the_classification())
    builder = Builder(store, fastf1=None, now=lambda: RACE_START + timedelta(hours=9))

    inputs = builder.gather(AUSTRIA)

    assert isinstance(inputs, Inputs)
    assert inputs.snapshot.complete
    assert inputs.classification_fingerprint == "sha256:result"


def test_timing_cut_short_is_held_back_by_the_build_too(tmp_path, monkeypatch):
    Jolpica(monkeypatch, laps={"1": 50, "2": 50, "3": 50})
    cut_short = make_session(laps_per_driver=50)
    cut_short.laps = cut_short.laps[cut_short.laps["LapNumber"] <= 1]
    cut_short.results["Laps"] = float("nan")
    store = archived(tmp_path, RACE_START + timedelta(hours=5), cut_short)
    builder = Builder(store, fastf1=None, now=lambda: RACE_START + timedelta(hours=9))

    held = builder.gather(AUSTRIA)

    assert isinstance(held, Hold)
    assert "timing_data" in held.reason


def test_a_session_nobody_archived_is_not_gathered(monkeypatch):
    Jolpica(monkeypatch)

    assert Builder(MemoryStore(), fastf1=None).gather(ITALY) is None


# --- after the window: rarely, and never for what F1 does not hold -------------


def test_after_the_window_a_short_session_is_still_fetched_but_rarely():
    """Found in review: fetching stopped for good at 48 hours, and rule 3 lets it
    stop only for a session that is complete."""
    first_fetch = RACE_START + timedelta(hours=5)
    short = snapshot(snapshot_id=fetched_at(first_fetch), session=without_position())
    schedule = [entry for entry in schedule_2026() if entry.round == 8]

    assert planned(schedule, [short], first_fetch + RETRY_WINDOW + timedelta(days=1)) == []
    assert planned(schedule, [short], first_fetch + SLOW_RETRY_INTERVAL) == [(8, "R")]

    again = snapshot(snapshot_id=fetched_at(first_fetch + SLOW_RETRY_INTERVAL), session=without_position())
    assert planned(schedule, [short, again], first_fetch + SLOW_RETRY_INTERVAL + timedelta(days=6)) == []
    assert planned(schedule, [short, again], first_fetch + 2 * SLOW_RETRY_INTERVAL) == [(8, "R")]


def test_a_feed_f1_says_it_does_not_hold_ends_the_retries_once_the_window_closes():
    """A race from before late 2024: F1 answers 403 for its pit-stop feed, and
    will whenever it is asked."""
    first_fetch = RACE_START + timedelta(hours=5)
    measurement = measure(make_session(), "R", {CIRCUIT_INFO: EXTRAS[CIRCUIT_INFO]})
    not_held = replace(
        snapshot(snapshot_id=fetched_at(first_fetch)),
        coverage=measurement,
        feed_status={"PitStopSeries.jsonStream": 403, "TimingData.jsonStream": 200},
    )
    schedule = [entry for entry in schedule_2026() if entry.round == 8]
    assert [shortfall.bar for shortfall in not_held.shortfalls()] == ["pit_stop_series"]

    # While the window is open the answer may only mean "not yet".
    assert planned(schedule, [not_held], first_fetch + RETRY_INTERVAL) == [(8, "R")]
    assert planned(schedule, [not_held], first_fetch + SLOW_RETRY_INTERVAL) == []
    assert planned(schedule, [not_held], first_fetch + 10 * SLOW_RETRY_INTERVAL) == []


def test_a_feed_that_was_answered_but_came_up_short_is_not_one_f1_does_not_hold():
    first_fetch = RACE_START + timedelta(hours=5)
    answered = replace(
        snapshot(snapshot_id=fetched_at(first_fetch), session=without_position()),
        feed_status={"Position.z.jsonStream": 200},
    )
    schedule = [entry for entry in schedule_2026() if entry.round == 8]

    assert not answered.missing_only_what_f1_does_not_hold()
    assert planned(schedule, [answered], first_fetch + SLOW_RETRY_INTERVAL) == [(8, "R")]


def test_a_correction_to_a_recent_result_makes_a_whole_snapshot_due_again():
    """Found in review: a snapshot once judged complete was skipped before the
    classification of today was looked at."""
    first_fetch = RACE_START + timedelta(hours=5)
    whole = snapshot(snapshot_id=fetched_at(first_fetch))
    schedule = [entry for entry in schedule_2026() if entry.round == 8]
    later = first_fetch + RETRY_INTERVAL
    asked = []

    def corrected(session):
        asked.append(session.round)
        return {"1": 11, "2": 10, "3": 10}

    assert planned(schedule, [whole], later) == []
    plans = plan_fetches(schedule, [whole], later, classified_laps=corrected)
    assert [plan.reason for plan in plans] == ["best of 1 snapshot(s) is short on car_data, position, timing_data, tyre_data"]
    assert asked == [8]


def test_only_recent_sessions_are_checked_against_the_classification_of_today():
    first_fetch = RACE_START + timedelta(hours=5)
    whole = snapshot(snapshot_id=fetched_at(first_fetch))
    schedule = [entry for entry in schedule_2026() if entry.round == 8]
    asked = []

    plan_fetches(schedule, [whole], LONG_AFTER, classified_laps=lambda session: asked.append(session.round))

    assert asked == []
