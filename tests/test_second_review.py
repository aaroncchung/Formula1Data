"""The cases the second review of this code found (GPT-6.1 Sol, 2026-10-06, at 723aef5).

Each test is one finding, reproduced. They are kept together because they are
the edges of rules whose ordinary cases are tested elsewhere: what happens to a
session months later, to a snapshot from before a bar existed, to a feed that
arrives broken.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from f1data import build as build_module
from f1data import layout
from f1data.archive import partial_publication_time, select_snapshot, write_snapshot
from f1data.build import Builder
from f1data.classification import Classification, ClassificationMissing, ClassificationUnavailable
from f1data.cli import main
from f1data.coverage import (
    MEASUREMENT_VERSION,
    Shortfall,
    apply_classification,
    evaluate_coverage,
    f1_does_not_hold,
)
from f1data.due import plan_fetches
from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES, circuit_corner_count, parse_pit_stop_series
from f1data.policy import CLASSIFICATION_RECHECK_WINDOW, RETRY_INTERVAL, RETRY_WINDOW, SLOW_RETRY_INTERVAL
from f1data.publish import Hold, Inputs, publish_session, read_pointer
from f1data.store import DirectoryStore, MemoryStore
from tests.fakes import EXTRAS, make_session, measure
from tests.test_archive import fetched_session
from tests.test_build_inputs import (
    AUSTRIA_RESULT,
    RACE_START,
    SOON_AFTER,
    World,
    a_quiet_day,
    a_recheck_day,
    archive,
    build_stub,
)
from tests.test_publish import AUSTRIA, Interposing, schedule_2026, snapshot

FIRST_FETCH = RACE_START + timedelta(hours=5)
ONE_RACE = [entry for entry in schedule_2026() if entry.round == 8]


def fetched_at(moment: datetime) -> str:
    return f"{moment.strftime('%Y%m%dT%H%M%SZ')}-aaaaaaaa"


def planned(snapshots, now, **kwargs):
    return [plan.session.round for plan in plan_fetches(ONE_RACE, snapshots, now, **kwargs)]


# --- B1: the calendar is a build input ----------------------------------------


def test_a_build_made_under_the_old_calendar_is_not_published_under_the_new_one(tmp_path, monkeypatch):
    """A builds with Austria at round 8. The calendar moves it to round 9 and B
    publishes from an older snapshot. A's snapshot and classification are
    unchanged, but its build has round 8 in it."""
    world = World(monkeypatch)
    store = Interposing(archive(tmp_path / "older"))
    write_snapshot(store, fetched_session(tmp_path / "newer"), now=FIRST_FETCH + timedelta(hours=1))
    a = Builder(store, fastf1=None, now=lambda: SOON_AFTER)

    def build_with_the_round_in_it(inputs):
        return {"summary.json": f"round {inputs.context.scheduled.round}".encode()}, None

    def calendar_changes_and_another_publisher_wins():
        world.renumber()
        older = min(a_store_snapshots(store), key=lambda item: item.fetched_at)
        publish_session(
            store,
            AUSTRIA,
            lambda key, **_: Inputs(older, AUSTRIA_RESULT["fingerprint"], also="someone else's calendar"),
            lambda inputs: ({"summary.json": b"from the older snapshot"}, None),
        )

    store.before_put[layout.pointer_key(AUSTRIA)] = calendar_changes_and_another_publisher_wins

    outcome = publish_session(store, AUSTRIA, a.gather, build_with_the_round_in_it)

    assert outcome.action == "published"
    pointer, _ = read_pointer(store, AUSTRIA)
    summary = store.get(f"{layout.generation_prefix(AUSTRIA, pointer.generation)}summary.json").data
    assert summary == b"round 9"


def a_store_snapshots(store):
    from f1data.archive import list_snapshots

    return list_snapshots(store, AUSTRIA)


# --- B2: a bar is part of the pipeline: see tests/test_layout.py -------------


# --- B3: a snapshot that was never judged is judged, however old ---------------


def test_a_snapshot_still_waiting_for_its_result_is_judged_when_the_machine_comes_back():
    """Fetched before Jolpica had the result, with timing cut to one lap; then
    the machine is off for a month."""
    cut_short = make_session(laps_per_driver=50)
    cut_short.laps = cut_short.laps[cut_short.laps["LapNumber"] <= 1]
    cut_short.results["Laps"] = float("nan")
    pending = snapshot(snapshot_id=fetched_at(FIRST_FETCH), session=cut_short)
    asked = []

    def result_of_today(session):
        asked.append(session.round)
        return {"1": 50, "2": 50, "3": 50}

    for days in (31, 38, 90):
        now = RACE_START + timedelta(days=days)
        assert planned([pending], now, classified_laps=result_of_today) == [8]
    assert asked == [8, 8, 8]


# --- B4: an old result is asked about less often, not never --------------------


def test_a_result_corrected_months_later_is_published_on_the_sessions_next_recheck_day(tmp_path, monkeypatch):
    world = World(monkeypatch)
    store = archive(tmp_path)
    clock = [SOON_AFTER]
    builder = Builder(store, fastf1=None, now=lambda: clock[0])
    publish_session(store, AUSTRIA, builder.gather, build_stub)
    world.results_by_round[8] = {"date": date(2026, 6, 28), "fingerprint": "sha256:corrected-in-october"}

    clock[0] = a_quiet_day(RACE_START + timedelta(days=100))
    assert publish_session(store, AUSTRIA, builder.gather, build_stub).action == "current"

    clock[0] = a_recheck_day(clock[0])
    outcome = publish_session(store, AUSTRIA, builder.gather, build_stub)
    assert (outcome.action, outcome.reason) == ("published", "the classification changed")
    assert clock[0] - a_quiet_day(RACE_START + timedelta(days=100)) <= timedelta(days=30)


def test_recheck_asks_about_every_session_whatever_the_day(tmp_path, monkeypatch):
    world = World(monkeypatch)
    store = archive(tmp_path)
    quiet = a_quiet_day(RACE_START + timedelta(days=100))
    publish_session(store, AUSTRIA, Builder(store, fastf1=None, now=lambda: SOON_AFTER).gather, build_stub)
    world.results_by_round[8] = {"date": date(2026, 6, 28), "fingerprint": "sha256:corrected"}

    outcome = publish_session(
        store, AUSTRIA, Builder(store, fastf1=None, now=lambda: quiet, recheck=True).gather, build_stub
    )

    assert outcome.action == "published"


def test_after_a_lost_write_an_old_session_is_looked_up_afresh(tmp_path, monkeypatch):
    world = World(monkeypatch)
    store = archive(tmp_path)
    quiet = a_quiet_day(RACE_START + timedelta(days=100))
    builder = Builder(store, fastf1=None, now=lambda: quiet)
    publish_session(store, AUSTRIA, Builder(store, fastf1=None, now=lambda: SOON_AFTER).gather, build_stub)
    pointer, _ = read_pointer(store, AUSTRIA)
    world.classification_requests.clear()

    builder.gather(AUSTRIA, pointer=pointer, retry=False)
    assert world.classification_requests == []
    builder.gather(AUSTRIA, pointer=pointer, retry=True)
    assert world.classification_requests == [8]


# --- B5: a result that never comes does not hold a session for ever ------------


class NoResult(World):
    def __init__(self, monkeypatch, error):
        super().__init__(monkeypatch)
        self.error = error

    def fetch_classification(self, fastf1, year, round_number, session_type):
        raise self.error


def without_a_result():
    session = make_session()
    session.results["Laps"] = float("nan")
    return session


def test_a_session_whose_result_never_arrives_is_published_as_partial_after_the_window(tmp_path, monkeypatch):
    NoResult(monkeypatch, ClassificationMissing("Jolpica has no classification for 2026 round 8 R"))
    store = MemoryStore()
    write_snapshot(store, fetched_session(tmp_path, without_a_result()), now=FIRST_FETCH)
    clock = [FIRST_FETCH + timedelta(hours=1)]
    builder = Builder(store, fastf1=None, now=lambda: clock[0])

    assert isinstance(builder.gather(AUSTRIA), Hold)

    clock[0] = FIRST_FETCH + RETRY_WINDOW
    inputs = builder.gather(AUSTRIA)
    assert isinstance(inputs, Inputs)
    assert inputs.classification_fingerprint is None
    assert {shortfall.bar for shortfall in inputs.snapshot.shortfalls()} == {"classification"}


def test_jolpica_not_answering_is_never_a_reason_to_publish_without_a_result(tmp_path, monkeypatch):
    NoResult(monkeypatch, ClassificationUnavailable("Jolpica did not return a classification"))
    store = MemoryStore()
    write_snapshot(store, fetched_session(tmp_path, without_a_result()), now=FIRST_FETCH)
    months_later = FIRST_FETCH + timedelta(days=120)

    assert isinstance(Builder(store, fastf1=None, now=lambda: months_later).gather(AUSTRIA), Hold)


# --- B6 and B8: the extra feeds are judged by what is in them -------------------


def test_a_pit_stop_with_nothing_in_it_is_not_a_pit_stop():
    assert parse_pit_stop_series(b'01:12:03.942{"PitTimes":{"1":[{}]}}') == []
    assert parse_pit_stop_series(b'01:12:03.942{"PitTimes":{"1":[{"PitStop":{"Lap":"12"}}]}}') == []
    session = make_session()

    found = evaluate_coverage(
        measure(session, "R", {**EXTRAS, PIT_STOP_SERIES: b'01:12:03.942{"PitTimes":{"1":[{}]}}'})
    )

    assert [shortfall.bar for shortfall in found] == ["pit_stop_series"]


def test_a_circuit_file_with_no_corners_is_not_corner_positions():
    assert circuit_corner_count(b'{"corners":[]}') == 0
    assert circuit_corner_count(b'{"corners":[{"number":1,"x":null,"y":2.0}]}') == 0
    assert circuit_corner_count(b"not json") == 0
    assert circuit_corner_count(EXTRAS[CIRCUIT_INFO]) == 1

    found = evaluate_coverage(measure(make_session(), "R", {**EXTRAS, CIRCUIT_INFO: b'{"corners":[]}'}))

    assert [shortfall.bar for shortfall in found] == ["circuit_info"]


@pytest.mark.parametrize(
    "feed",
    [
        b"01:12:03.942null",
        b'01:12:03.942{"PitTimes":{"1":[null]}}',
        b'01:12:03.942{"PitTimes":{"1":"not a list"}}',
        b'01:12:03.942{"PitTimes":[1,2,3]}',
        b'01:12:03.942{"PitTimes":{"1":[{"PitStop":{"Lap":"12","PitStopTime":"Infinity"}}]}}',
        b'01:12:03.942{"PitTimes":{"1":[{"PitStop":{"Lap":"1e999","PitLaneTime":"21.3"}}]}}',
        bytes([0xFF, 0xFE, 0x00, 0x80]) + b'{"PitTimes":{}}',
        b"",
    ],
)
def test_a_broken_pit_stop_feed_costs_nothing_but_itself(feed, tmp_path):
    """It is read while a fetch is measured, before the fetch is archived: an
    exception here used to lose every feed that had arrived whole."""
    assert parse_pit_stop_series(feed) == []

    measurement = measure(make_session(), "R", {**EXTRAS, PIT_STOP_SERIES: feed})

    assert measurement["pit_stops_in_series"] == 0


def test_a_duration_that_is_not_a_duration_is_left_out_and_the_stop_kept():
    feed = b'01:12:03.942{"PitTimes":{"1":[{"PitStop":{"Lap":"12","PitStopTime":"NaN","PitLaneTime":"21.3"}}]}}'

    (stop,) = parse_pit_stop_series(feed)

    assert (stop["stationary_ms"], stop["pit_lane_ms"]) == (None, 21300)


# --- B7: snapshots from before a feed was collected ----------------------------


def old_measurement(snapshot_id, session=None):
    old = snapshot(snapshot_id=snapshot_id, session=session)
    coverage = {**old.coverage, "measurement_version": MEASUREMENT_VERSION - 1}
    for key in ("pit_stops_in_timing", "pit_stops_in_series", "circuit_corners"):
        coverage.pop(key, None)
    coverage["feeds"] = {k: v for k, v in coverage["feeds"].items() if k not in {"pit_stop_series", "circuit_info"}}
    return replace(old, coverage=coverage)


def test_a_snapshot_from_before_a_feed_was_collected_does_not_outrank_one_measured_in_full():
    """Its missing counts read as zero, so it used to look better than it could
    be known to be. What it lacks cannot be counted, so it is not compared by
    count with one whose shortfalls can."""
    old = old_measurement(fetched_at(FIRST_FETCH))
    damaged = make_session()
    damaged.weather_data = damaged.weather_data.iloc[0:0]
    damaged.race_control_messages = damaged.race_control_messages.iloc[0:0]
    damaged.track_status = damaged.track_status.iloc[0:0]
    new = snapshot(snapshot_id=fetched_at(FIRST_FETCH + timedelta(days=30)), session=damaged)

    assert "measurement" in {shortfall.bar for shortfall in old.shortfalls()}
    assert len(new.shortfalls()) > len(old.shortfalls())
    assert select_snapshot([old, new]) == new
    # A whole one still beats both.
    whole = snapshot(snapshot_id=fetched_at(FIRST_FETCH + timedelta(days=31)))
    assert select_snapshot([old, new, whole]) == whole


def test_the_partial_publication_window_runs_from_the_first_fetch_measured_in_full():
    old = old_measurement(fetched_at(FIRST_FETCH))
    refetched = FIRST_FETCH + timedelta(days=30)
    new = snapshot(snapshot_id=fetched_at(refetched))

    assert partial_publication_time([old, new]) == refetched + RETRY_WINDOW
    assert partial_publication_time([old]) == FIRST_FETCH + RETRY_WINDOW


# --- B9: a refusal is not proof of absence -------------------------------------


def test_a_feed_refused_by_an_origin_that_was_refusing_everything_is_not_one_f1_does_not_hold():
    missing = Shortfall("pit_stop_series", None, "no stationary times")
    answering = {"SessionInfo.jsonStream": 200, "PitStopSeries.jsonStream": 403}
    refusing = {"SessionInfo.jsonStream": 403, "PitStopSeries.jsonStream": 403}

    absent = {"feeds": {"pit_stop_series": False}}

    assert f1_does_not_hold(missing, answering, absent)
    assert not f1_does_not_hold(missing, refusing, absent)
    assert not f1_does_not_hold(missing, {}, absent)


def test_a_feed_that_arrived_and_is_short_for_a_driver_is_never_one_f1_does_not_hold():
    """F1 refuses its position feed, the mirror supplies it, and one driver is short."""
    short_for_a_driver = Shortfall("position", "AAA", "4 of 78 expected laps usable")
    status = {"SessionInfo.jsonStream": 200, "Position.z.jsonStream": 403}

    assert not f1_does_not_hold(short_for_a_driver, status, {"feeds": {"position": True}})

    damaged = make_session()
    del damaged.pos_data["1"]
    stuck = replace(snapshot(snapshot_id=fetched_at(FIRST_FETCH), session=damaged), feed_status=status)
    assert planned([stuck], FIRST_FETCH + SLOW_RETRY_INTERVAL) == [8]


# --- B11: a copy is checked by content -----------------------------------------


def test_copy_archive_replaces_an_object_of_the_right_size_and_the_wrong_bytes(tmp_path, capsys):
    spool, bucket = DirectoryStore(tmp_path / "spool"), DirectoryStore(tmp_path / "bucket")
    written = write_snapshot(spool, fetched_session(tmp_path))
    main_quietly(["copy-archive", "--from", str(tmp_path / "spool"), "--to", str(tmp_path / "bucket")])
    key = f"{layout.snapshot_prefix(AUSTRIA, written.snapshot_id)}extra/circuit-info.json"
    right = bucket.get(key).data
    bucket.put(key, bytes(len(right)))
    capsys.readouterr()

    main_quietly(["copy-archive", "--from", str(tmp_path / "spool"), "--to", str(tmp_path / "bucket")])

    assert "Copied 1 object(s); 4 already there." in capsys.readouterr().out
    assert bucket.get(key).data == right


def main_quietly(arguments):
    with pytest.raises(SystemExit) as finished:
        main(arguments)
    assert finished.value.code == 0


# --- B12 and B13 ----------------------------------------------------------------


def test_the_result_of_today_is_the_whole_answer_for_every_driver():
    stored = measure(make_session())

    judged = apply_classification(stored, {"1": 10, "2": 10})

    # Driver 3 is not in today's result: not classified, so no laps to account for.
    assert judged["drivers"]["CCC"]["classified_laps"] == 0
    assert evaluate_coverage(judged) == []


def test_a_driver_listed_by_f1_and_not_classified_is_not_short_for_ever():
    session = make_session()
    session.results["Laps"] = float("nan")
    session.laps = session.laps[session.laps["DriverNumber"] != "3"]
    del session.car_data["3"]
    del session.pos_data["3"]
    stored = measure(session)
    assert ("classification", "CCC") in {(item.bar, item.driver) for item in evaluate_coverage(stored)}

    assert evaluate_coverage(apply_classification(stored, {"1": 10, "2": 10})) == []


def test_the_tyre_bar_does_not_need_a_tyre_age_column():
    session = make_session()
    session.laps = session.laps.drop(columns=["TyreLife"])

    measurement = measure(session)

    assert measurement["drivers"]["AAA"]["tyre_laps"] == 10
    assert measurement["drivers"]["AAA"]["tyre_age_laps"] == 0
    assert evaluate_coverage(measurement) == []
