"""The cases the third review of this code found (GPT-6.1 Sol, 2026-10-06, at 9d857fb).

Each test is one finding, reproduced. Most are about two things that are
meant to agree and had come apart: the calendar a publisher decided from and
the one in force when it wrote, the result a session was judged against and
the one built into it, what the archive records of a snapshot and what a build
finds in it.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from f1data import cli as cli_module
from f1data import layout
from f1data.archive import list_snapshots, write_snapshot
from f1data.build import Builder
from f1data.classification import fetch_classification, merge_into_session
from f1data.cli import main
from f1data.coverage import evaluate_coverage
from f1data.due import plan_fetches
from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES, parse_pit_stop_series
from f1data.policy import RETRY_INTERVAL, RETRY_WINDOW, SLOW_RETRY_INTERVAL
from f1data.publish import Hold, Inputs, publish_index, publish_session, read_pointer
from f1data.store import DirectoryStore, MemoryStore
from tests.building import Archive
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
from tests.test_classification import Jolpica as JolpicaClient
from tests.test_classification import result_frame
from tests.test_publish import AUSTRIA, Interposing, snapshot
from tests.test_second_review import FIRST_FETCH, ONE_RACE, fetched_at, planned


def calendar_entry(round_number: int) -> dict:
    return {
        "calendar": {
            "year": 2026,
            "round": round_number,
            "meeting_name": "Austrian Grand Prix",
            "session_name": "Race",
            "row": None,
        }
    }


def build_with_the_round_in_it(inputs):
    return {"summary.json": f"round {inputs.context.scheduled.round}".encode()}, None


def published_summary(store) -> bytes:
    pointer, _ = read_pointer(store, AUSTRIA)
    return store.get(f"{layout.generation_prefix(AUSTRIA, pointer.generation)}summary.json").data


def index_rounds(store) -> list[int]:
    index = json.loads(store.get(layout.index_key()).data)
    return [meeting["round"] for meeting in index["seasons"][0]["meetings"]]


# --- C1: the calendar entry is something a session was built from ---------------


def test_a_session_is_built_again_when_only_its_calendar_entry_changes(tmp_path, monkeypatch):
    """The same snapshot and the same result, and a race inserted ahead of this
    one: what is published still says round 8, under an index that says 9."""
    world = World(monkeypatch)
    store = archive(tmp_path)
    builder = Builder(store, fastf1=None, now=lambda: SOON_AFTER)
    publish_session(store, AUSTRIA, builder.gather, build_with_the_round_in_it)
    assert published_summary(store) == b"round 8"
    assert read_pointer(store, AUSTRIA)[0].also == calendar_entry(8)

    world.renumber()
    outcome = publish_session(store, AUSTRIA, builder.gather, build_with_the_round_in_it)

    assert (outcome.action, outcome.reason) == ("published", "the calendar entry changed")
    assert published_summary(store) == b"round 9"
    assert read_pointer(store, AUSTRIA)[0].also == calendar_entry(9)
    assert publish_session(store, AUSTRIA, builder.gather, build_with_the_round_in_it).action == "current"


def test_an_old_session_is_built_again_when_its_calendar_entry_changes(tmp_path, monkeypatch):
    """Between the days its result is asked about, an old session is still
    looked up in the calendar."""
    world = World(monkeypatch)
    store = archive(tmp_path)
    publish_session(
        store, AUSTRIA, Builder(store, fastf1=None, now=lambda: SOON_AFTER).gather, build_with_the_round_in_it
    )
    quiet = a_quiet_day(RACE_START + timedelta(days=100))
    builder = Builder(store, fastf1=None, now=lambda: quiet)
    world.classification_requests.clear()

    assert publish_session(store, AUSTRIA, builder.gather, build_with_the_round_in_it).action == "current"
    assert world.classification_requests == []

    world.renumber()
    outcome = publish_session(store, AUSTRIA, builder.gather, build_with_the_round_in_it)

    assert (outcome.action, outcome.reason) == ("published", "the calendar entry changed")
    assert published_summary(store) == b"round 9"


def test_a_publisher_that_lost_to_a_build_from_the_old_calendar_publishes_its_own(tmp_path, monkeypatch):
    """A builds with Austria at round 9. B, which still has the old calendar,
    wins the pointer write with the same snapshot and the same result at round
    8. A reads again and finds nothing changed but the calendar entry."""
    world = World(monkeypatch)
    world.renumber()
    store = Interposing(archive(tmp_path))
    a = Builder(store, fastf1=None, now=lambda: SOON_AFTER)
    (only,) = list_snapshots(store, AUSTRIA)

    def b_publishes_from_the_old_calendar():
        outcome = publish_session(
            store,
            AUSTRIA,
            lambda key, **_: Inputs(only, AUSTRIA_RESULT["fingerprint"], also=calendar_entry(8)),
            lambda inputs: ({"summary.json": b"round 8"}, None),
        )
        assert outcome.action == "published"

    store.before_put[layout.pointer_key(AUSTRIA)] = b_publishes_from_the_old_calendar

    outcome = publish_session(store, AUSTRIA, a.gather, build_with_the_round_in_it)

    assert outcome.action == "published"
    assert published_summary(store) == b"round 9"


# --- C3: the calendar is read after the version a write is guarded by -----------


def test_the_index_is_not_derived_from_a_calendar_read_earlier_in_the_run(tmp_path, monkeypatch):
    """Part A read the calendar while it built its sessions. The calendar then
    changed and part B derived the index from it. A derives the index next: it
    reads B's, so its own write would not conflict, and from the calendar it
    was holding it would put the old rounds back."""
    world = World(monkeypatch)
    store = archive(tmp_path)
    a = Builder(store, fastf1=None, now=lambda: SOON_AFTER)
    b = Builder(store, fastf1=None, now=lambda: SOON_AFTER)
    publish_session(store, AUSTRIA, a.gather, build_stub)
    world.renumber()
    assert publish_index(store, b.schedule) == "published"
    assert index_rounds(store) == [9, 15]

    assert publish_index(store, a.schedule) == "current"

    assert index_rounds(store) == [9, 15]


def test_a_session_is_not_built_from_a_calendar_read_earlier_in_the_run(tmp_path, monkeypatch):
    """The same for a pointer: A has been running since before the calendar
    changed, and comes to a session B has just published from the new one."""
    world = World(monkeypatch)
    store = archive(tmp_path)
    a = Builder(store, fastf1=None, now=lambda: SOON_AFTER)
    b = Builder(store, fastf1=None, now=lambda: SOON_AFTER)
    assert a.schedule(2026)[1].round == 8
    world.renumber()
    assert publish_session(store, AUSTRIA, b.gather, build_with_the_round_in_it).action == "published"

    outcome = publish_session(store, AUSTRIA, a.gather, build_with_the_round_in_it)

    assert outcome.action == "current"
    assert published_summary(store) == b"round 9"


# --- C2: today's result is the whole answer in the build too --------------------


def test_a_driver_todays_result_leaves_out_keeps_no_result_from_the_archive():
    """The session loads with three drivers classified. Today's result has two."""
    session = SimpleNamespace(
        results=pd.DataFrame(
            {
                "DriverNumber": ["63", "3", "77"],
                "Abbreviation": ["RUS", "VER", "BOT"],
                "TeamColor": ["27F4D2", "3671C6", "909090"],
                "Position": [1.0, 2.0, 3.0],
                "ClassifiedPosition": ["1", "2", "3"],
                "GridPosition": [1.0, 5.0, 20.0],
                "Status": ["Finished", "Finished", "Finished"],
                "Points": [25.0, 18.0, 15.0],
                "Time": [pd.Timedelta(hours=1), pd.Timedelta(seconds=2), pd.Timedelta(seconds=9)],
                "Laps": [71.0, 71.0, 71.0],
            },
            index=["63", "3", "77"],
        )
    )
    todays = result_frame().iloc[:2]

    merge_into_session(session, fetch_classification(JolpicaClient([todays]), 2026, 8, "R"))

    merged = session._results
    assert list(merged["Abbreviation"]) == ["RUS", "VER", "BOT"]
    left_out = merged.loc["77"]
    for column in ("Position", "GridPosition", "Points", "Time", "Laps"):
        assert pd.isna(left_out[column]), column
    assert (left_out["ClassifiedPosition"], left_out["Status"]) == ("", "")
    # Who the driver is does not come from the result.
    assert (left_out["Abbreviation"], left_out["TeamColor"]) == ("BOT", "909090")
    assert list(merged.loc[["63", "3"], "Laps"]) == [71, 71]


def test_a_driver_the_result_leaves_out_is_no_fault_in_the_record(tmp_path, monkeypatch):
    """Driver 3 has ten laps in the archive and is not in today's result. The
    snapshot was judged whole on that footing, and the pointer says what was
    judged. The record is about the feeds, and the feeds are as recorded."""
    world = Archive(monkeypatch, {"1": 10, "2": 10})
    world.snapshot(tmp_path)
    builder = Builder(world.store, fastf1=None, now=lambda: SOON_AFTER)

    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    pointer, _ = read_pointer(world.store, AUSTRIA)
    assert (pointer.complete, pointer.shortfalls) == (True, [])
    assert not [item.key for item in world.store.list("archive/") if item.key.endswith("remeasured.json")]
    # And the session the artifacts were made from has no result for that driver.
    (built,) = world.built
    assert pd.isna(built.results.loc["3", "Laps"]) and built.results.loc["1", "Laps"] == 10


# --- C4: a session published short is looked at again, however old --------------


def test_a_result_corrected_months_later_makes_the_session_due_for_another_fetch(tmp_path, monkeypatch):
    """Whole when fetched, with ten laps a driver. A hundred days on Jolpica
    gives one driver eleven, and the session is published short of that lap.
    The archive's record of the snapshot has not changed: only the pointer
    says the session is short."""
    result = Archive(monkeypatch, {"1": 10, "2": 10, "3": 10})
    result.snapshot(tmp_path)
    store = result.store
    clock = [SOON_AFTER]
    builder = Builder(store, fastf1=None, now=lambda: clock[0])
    publish = lambda: publish_session(store, AUSTRIA, builder.gather, build_stub, now=lambda: clock[0])
    assert publish().action == "published"
    assert cli_module._published_short(store) == set()

    result.laps["1"] = 11
    clock[0] = a_recheck_day(RACE_START + timedelta(days=100))
    assert publish().action == "published"
    assert read_pointer(store, AUSTRIA)[0].complete is False
    short = cli_module._published_short(store)
    assert short == {AUSTRIA}

    asked = []

    def result_of_today(session):
        asked.append(session.round)
        return dict(result.laps)

    snapshots = list_snapshots(store)
    assert plan_fetches(ONE_RACE, snapshots, clock[0], result_of_today) == []
    assert asked == []
    for days in (0, 30, 60):
        plans = plan_fetches(
            ONE_RACE, snapshots, clock[0] + timedelta(days=days), result_of_today, published_short=short
        )
        assert [plan.reason for plan in plans] == [
            "best of 1 snapshot(s) is short on car_data, position, timing_data, tyre_data"
        ]
    assert asked == [8, 8, 8]


def test_fetch_due_looks_again_at_a_session_published_short(tmp_path, monkeypatch, capsys):
    """The same, through the command: what is published reaches the planner."""
    store = DirectoryStore(tmp_path / "bucket")
    write_snapshot(store, fetched_session(tmp_path), now=FIRST_FETCH)

    @contextmanager
    def no_cache(cache_dir):
        yield None

    monkeypatch.setattr(cli_module, "fastf1_cache", no_cache)
    monkeypatch.setattr(cli_module, "load_schedule", lambda fastf1, year: ONE_RACE)
    monkeypatch.setattr(
        cli_module,
        "fetch_classified_laps",
        lambda fastf1, year, round_number, session_type: {"1": 11, "2": 10, "3": 10},
    )
    arguments = ["fetch-due", "--store", str(tmp_path / "bucket"), "--season", "2026", "--dry-run"]

    with pytest.raises(SystemExit):
        main(arguments)
    assert "Nothing to fetch" in capsys.readouterr().out

    (whole,) = list_snapshots(store)
    short = whole.judged_against({"1": 11, "2": 10, "3": 10})
    publish_session(
        store,
        AUSTRIA,
        lambda key, **_: Inputs(short, "sha256:corrected"),
        lambda inputs: ({"summary.json": b"{}\n"}, None),
    )

    with pytest.raises(SystemExit):
        main(arguments)
    assert "2026 round 8 Austrian Grand Prix Race: best of 1 snapshot(s) is short on" in capsys.readouterr().out


# --- C5: what the archive records and what a build finds ------------------------


def from_before_corners_were_counted(tmp_path, circuit_file: bytes) -> MemoryStore:
    fetched = fetched_session(tmp_path)
    del fetched.coverage["circuit_corners"]
    fetched.extras[CIRCUIT_INFO] = circuit_file
    store = MemoryStore()
    write_snapshot(store, fetched, now=FIRST_FETCH)
    return store


def test_a_corner_count_that_is_absent_does_not_pass():
    measurement = measure(make_session())
    del measurement["circuit_corners"]

    assert [shortfall.bar for shortfall in evaluate_coverage(measurement)] == ["circuit_info"]


def test_a_snapshot_from_before_corners_were_counted_has_them_counted_from_its_file(tmp_path, monkeypatch):
    store = from_before_corners_were_counted(tmp_path / "with", EXTRAS[CIRCUIT_INFO])

    (listed,) = list_snapshots(store, AUSTRIA)

    assert listed.coverage["circuit_corners"] == 1
    assert listed.complete

    # The file arrived, and has no corner in it.
    store = from_before_corners_were_counted(tmp_path / "without", b'{"corners":[]}')

    (listed,) = list_snapshots(store, AUSTRIA)

    assert listed.coverage["circuit_corners"] == 0
    assert [shortfall.bar for shortfall in listed.shortfalls()] == ["circuit_info"]
    # So it is fetched again, and held back while it may still improve.
    assert planned([listed], FIRST_FETCH + RETRY_INTERVAL) == [8]
    World(monkeypatch)
    held = Builder(store, fastf1=None, now=lambda: FIRST_FETCH + timedelta(hours=1)).gather(AUSTRIA)
    assert isinstance(held, Hold) and "circuit_info" in held.reason


def test_a_build_that_finds_its_snapshot_short_waits_like_any_other_short_session(tmp_path, monkeypatch):
    """The record says whole. The feeds themselves, measured by the build,
    have no positions for one driver. The record is corrected and the decision
    taken again from it, so rule 6 holds as for any short session: nothing is
    published while later fetches may do better, and they are asked for."""
    world = Archive(monkeypatch, {"1": 10, "2": 10, "3": 10})
    damaged = make_session()
    del damaged.pos_data["2"]
    world.snapshot(tmp_path, recorded=make_session(), feeds=damaged)
    store = world.store
    clock = [FIRST_FETCH + timedelta(hours=1)]
    builder = Builder(store, fastf1=None, now=lambda: clock[0])
    assert isinstance(builder.gather(AUSTRIA), Inputs)

    waiting = publish_session(store, AUSTRIA, builder.gather, builder.build)

    assert waiting.action == "waiting"
    assert waiting.reason.startswith("short on position; to be fetched again")
    assert read_pointer(store, AUSTRIA) == (None, None)
    assert world.built == []
    # Every reader of the archive now sees what the feeds hold, the fetch
    # planner among them: the retries happen while the window is open.
    (corrected,) = list_snapshots(store)
    assert [(item.bar, item.driver) for item in corrected.shortfalls()] == [("position", "BBB")]
    assert planned([corrected], FIRST_FETCH + RETRY_INTERVAL) == [8]

    clock[0] = FIRST_FETCH + RETRY_WINDOW
    published = publish_session(store, AUSTRIA, builder.gather, builder.build)

    assert published.action == "published"
    pointer, _ = read_pointer(store, AUSTRIA)
    assert pointer.complete is False
    assert [item["bar"] for item in pointer.shortfalls] == ["position"]
    # Published short, and fetched again for as long as it is.
    for weeks in (1, 5, 20):
        assert planned(list_snapshots(store), FIRST_FETCH + weeks * SLOW_RETRY_INTERVAL) == [8]


# --- C6: a feed that arrived is not one F1 does not hold -------------------------


def test_a_feed_that_arrived_unfinished_is_not_one_f1_does_not_hold():
    """F1 refuses the session status, the mirror supplies it, and it stops
    before the end of the session."""
    status = {"SessionInfo.jsonStream": 200, "SessionStatus.jsonStream": 403}
    unfinished = make_session()
    unfinished.session_status = pd.DataFrame({"Status": ["Inactive", "Started"]})
    stuck = replace(snapshot(snapshot_id=fetched_at(FIRST_FETCH), session=unfinished), feed_status=status)
    assert [(item.bar, item.driver) for item in stuck.shortfalls()] == [("session_status", None)]
    assert stuck.coverage["feeds"]["session_status"] is True

    assert not stuck.missing_only_what_f1_does_not_hold()
    assert planned([stuck], FIRST_FETCH + SLOW_RETRY_INTERVAL) == [8]

    # The same answers with no feed at all: that one F1 does not hold.
    absent = make_session()
    absent.session_status = absent.session_status.iloc[0:0]
    gone = replace(snapshot(snapshot_id=fetched_at(FIRST_FETCH), session=absent), feed_status=status)
    assert [(item.bar, item.driver) for item in gone.shortfalls()] == [("session_status", None)]

    assert gone.missing_only_what_f1_does_not_hold()
    assert planned([gone], FIRST_FETCH + SLOW_RETRY_INTERVAL) == []


# --- C7: a number is not a duration because it is finite ------------------------


@pytest.mark.parametrize("duration", ["1e308", "1e300", "86401", "-0.5"])
def test_a_duration_too_long_to_be_one_is_left_out(duration):
    def feed(stop: str) -> bytes:
        return f'01:12:03.942{{"PitTimes":{{"1":[{{"PitStop":{{{stop}}}}}]}}}}'.encode()

    (stop,) = parse_pit_stop_series(feed(f'"Lap":"12","PitStopTime":"{duration}","PitLaneTime":"21.3"'))
    assert (stop["stationary_ms"], stop["pit_lane_ms"]) == (None, 21300)

    alone = feed(f'"Lap":"12","PitStopTime":"{duration}"')
    assert parse_pit_stop_series(alone) == []
    assert measure(make_session(), "R", {**EXTRAS, PIT_STOP_SERIES: alone})["pit_stops_in_series"] == 0
