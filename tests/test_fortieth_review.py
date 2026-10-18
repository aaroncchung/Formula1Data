"""The cases the fortieth review of this code found (a comment on pull request 11, 2026-10-12, at bc12b0f).

Two findings, of the second rank, both in what the round before added.

A measurement counted the laps a feed can be relied on for, and only the
order of two snapshots read the count. A session was complete on two bars
taken one at a time: at most one lap in twenty missing, and at most one in
twenty repeating itself. Two of forty missing and two others repeating met
both with 36 laps of 40 to rely on, and a session that is complete is not
fetched again.

And a record from before those laps were counted has every lap that repeats
taken off its usable ones, which is too few where a lap has a hole in it as
well. Too few put the better of two snapshots second, the build counted only
the one it took, and the one passed over stayed passed over.

The laps to be relied on are now held to the share the usable laps are. And a
build counts what the record of every other snapshot of the session lacks
before it makes anything of the one it took, and decides again.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from f1data import build as build_module
from f1data import layout
from f1data.archive import list_snapshots, select_snapshot, write_snapshot
from f1data.build import Builder
from f1data.coverage import CAR_REPEATS_BAR, counted_in_full, evaluate_coverage, weakest_share
from f1data.due import plan_fetches
from f1data.policy import RETRY_INTERVAL
from f1data.publish import publish_session, read_pointer
from tests.building import Archive
from tests.fakes import measure
from tests.test_archive import fetched_session
from tests.test_fifth_review import WINDOW_CLOSED, correction, correction_key
from tests.test_publish import AUSTRIA, schedule_2026, snapshot
from tests.test_thirty_fifth_review import shortfalls
from tests.test_thirty_ninth_review import (
    EVERYONE,
    before_reliable_laps_were_counted,
    car_figures,
    position_figures,
    race,
)

# --- 1: laps missing and other laps repeating are one tolerance, not two -----------


def test_two_laps_missing_and_two_others_repeating_are_four_that_cannot_be_relied_on():
    """The finding. Thirty-eight usable laps of forty is the bar, and two
    that repeat are as many as may. Thirty-six is nine in ten."""
    measurement = measure(race(car_holes={"1": [5, 6]}, car_repeats={"1": [9, 10]}))
    assert car_figures(measurement) == (38, 2, 36)

    (short,) = evaluate_coverage(measurement)
    assert (short.bar, short.driver) == ("car_data", "AAA")
    assert short.detail == (
        "36 of 40 expected laps can be relied on: 38 are usable, and F1's car feed repeats itself on 2 of those"
    )


def test_the_position_feed_is_held_to_the_same():
    measurement = measure(race(position_holes={"2": [5, 6]}, position_repeats={"2": [9, 10]}))
    assert position_figures(measurement, "BBB") == (38, 2, 36)

    assert shortfalls(measurement) == {("position", "BBB")}


def test_the_same_laps_missing_and_repeating_are_still_within_the_tolerance():
    """Two laps that are bad both ways are two laps."""
    measurement = measure(race(car_holes={"1": [5, 6]}, car_repeats={"1": [5, 6]}))
    assert car_figures(measurement) == (38, 2, 38)

    assert evaluate_coverage(measurement) == []


def test_a_feed_that_is_short_already_is_not_said_to_be_short_twice():
    """One feed short for one driver is one shortfall, however it is short:
    the order of two snapshots counts them."""
    missing = measure(race(car_holes={"1": [5, 6, 7]}, car_repeats={"1": [9, 10]}))
    repeating = measure(race(car_holes={"1": [5, 6]}, car_repeats={"1": [9, 10, 11]}))
    assert car_figures(missing) == (37, 2, 35) and car_figures(repeating) == (38, 3, 35)

    assert [(item.bar, item.driver) for item in evaluate_coverage(missing)] == [("car_data", "AAA")]
    assert [(item.bar, item.driver) for item in evaluate_coverage(repeating)] == [(CAR_REPEATS_BAR, "AAA")]


def test_a_record_that_does_not_count_the_laps_to_rely_on_is_not_judged_by_them():
    """A count that is absent was never taken. A build counts it before it
    publishes anything from the snapshot."""
    counted = measure(race(car_holes={"1": [5, 6]}, car_repeats={"1": [9, 10]}))
    older = before_reliable_laps_were_counted(counted)

    assert not counted_in_full(older) and counted_in_full(counted)
    assert evaluate_coverage(older) == [] and evaluate_coverage(counted) != []


def test_such_a_session_is_not_complete_and_is_fetched_again():
    """The finding's consequence. A session one of whose snapshots is
    complete is never asked for again."""
    short = snapshot(session=race(car_holes={"1": [5, 6]}, car_repeats={"1": [9, 10]})).judged_against(EVERYONE)
    assert not short.complete
    fetched = short.identity.start_time + timedelta(hours=5)
    short = replace(short, fetched_at=fetched.strftime("%Y-%m-%dT%H:%M:%SZ"))

    plans = plan_fetches(schedule_2026(), [short], fetched + RETRY_INTERVAL, classified_laps=lambda session: EVERYONE)

    assert [(plan.session.round, plan.reason) for plan in plans] == [
        (8, "best of 1 snapshot(s) is short on car_data")
    ]


def test_it_is_published_as_partial_and_says_what_is_short(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path, race(car_holes={"1": [5, 6]}, car_repeats={"1": [9, 10]}), moment=WINDOW_CLOSED)

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED + timedelta(days=3))
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    pointer = read_pointer(world.store, AUSTRIA)[0]
    assert not pointer.complete and pointer.pipeline_version == layout.PIPELINE_VERSION >= 27
    assert [(item["bar"], item["driver"]) for item in pointer.shortfalls] == [("car_data", "AAA")]


# --- 2: every snapshot of a session is counted before one is taken -----------------


def two_fetches(world, tmp_path):
    """The finding's two. The earlier has 37 laps of car data to rely on, two
    of its three bad laps bad both ways, and a record from before that was
    counted: 37 usable less 2 that repeat. The later has 36."""
    better = race(car_holes={"1": [5, 6, 7]}, car_repeats={"1": [6, 7]})
    fetched = fetched_session(tmp_path / "earlier", better)
    earlier = write_snapshot(
        world.store, replace(fetched, coverage=before_reliable_laps_were_counted(fetched.coverage)), now=WINDOW_CLOSED
    )
    world.feeds[earlier.snapshot_id] = better
    (tmp_path / "later").mkdir()
    later = world.snapshot(
        tmp_path / "later", race(car_holes={"1": [5, 6, 7, 8]}), moment=WINDOW_CLOSED + timedelta(hours=6)
    )
    return earlier, later


def shares(world) -> dict[str, float]:
    return {
        listed.snapshot_id: weakest_share(listed.judged_against(EVERYONE).coverage)
        for listed in list_snapshots(world.store)
    }


def test_a_snapshot_passed_over_on_a_guess_is_counted_and_taken(tmp_path, monkeypatch):
    """The finding. By its record the earlier stands at 35 laps of 40 and the
    later at 36, so the later is taken, and was built and published. The
    earlier has 37."""
    (tmp_path / "earlier").mkdir()
    world = Archive(monkeypatch, EVERYONE)
    earlier, later = two_fetches(world, tmp_path)
    assert shares(world) == {earlier.snapshot_id: 35 / 40, later.snapshot_id: 36 / 40}
    assert select_snapshot([item.judged_against(EVERYONE) for item in list_snapshots(world.store)]) == later

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED + timedelta(days=3))
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert read_pointer(world.store, AUSTRIA)[0].snapshot_id == earlier.snapshot_id
    assert car_figures(correction(world.store, earlier)["coverage"]) == (37, 2, 37)
    assert shares(world) == {earlier.snapshot_id: 37 / 40, later.snapshot_id: 36 / 40}
    # The later was never built from: one generation, of the earlier's feeds.
    assert len(world.built) == 1
    assert world.store.get(correction_key(later)) is None


def test_it_stays_taken_on_the_next_run_and_nothing_is_loaded_for_it(tmp_path, monkeypatch):
    (tmp_path / "earlier").mkdir()
    world = Archive(monkeypatch, EVERYONE)
    earlier, _ = two_fetches(world, tmp_path)
    clock = lambda: WINDOW_CLOSED + timedelta(days=3)  # noqa: E731
    first = Builder(world.store, fastf1=None, now=clock)
    publish_session(world.store, AUSTRIA, first.gather, first.build)
    loaded = len(world.loaded)

    again = Builder(world.store, fastf1=None, now=clock)
    outcome = publish_session(world.store, AUSTRIA, again.gather, again.build)

    assert outcome.action == "current" and len(world.loaded) == loaded
    assert read_pointer(world.store, AUSTRIA)[0].snapshot_id == earlier.snapshot_id


def test_a_snapshot_that_is_counted_and_is_still_the_worse_changes_nothing(tmp_path, monkeypatch):
    """Counted all the same, so that the next choice is not made on a guess."""
    (tmp_path / "earlier").mkdir()
    world = Archive(monkeypatch, EVERYONE)
    worse = race(car_holes={"1": [5, 6, 7, 8, 9]}, car_repeats={"1": [8, 9]})
    fetched = fetched_session(tmp_path / "earlier", worse)
    earlier = write_snapshot(
        world.store, replace(fetched, coverage=before_reliable_laps_were_counted(fetched.coverage)), now=WINDOW_CLOSED
    )
    world.feeds[earlier.snapshot_id] = worse
    (tmp_path / "later").mkdir()
    later = world.snapshot(
        tmp_path / "later", race(car_holes={"1": [5, 6, 7, 8]}), moment=WINDOW_CLOSED + timedelta(hours=6)
    )

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED + timedelta(days=3))
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert read_pointer(world.store, AUSTRIA)[0].snapshot_id == later.snapshot_id
    assert shares(world) == {earlier.snapshot_id: 35 / 40, later.snapshot_id: 36 / 40}
    assert car_figures(correction(world.store, earlier)["coverage"]) == (35, 2, 35)


def test_a_snapshot_that_will_not_load_does_not_stop_the_one_that_was_taken(tmp_path, monkeypatch, caplog):
    """Nothing is built from it. It is judged by its record as it stands,
    and loaded for this once in a run."""
    (tmp_path / "earlier").mkdir()
    world = Archive(monkeypatch, EVERYONE)
    earlier, later = two_fetches(world, tmp_path)
    restore = world._restore
    tried: list[str] = []

    def broken(store, snap, cache_dir):
        if snap.snapshot_id == earlier.snapshot_id:
            tried.append(snap.snapshot_id)
            raise build_module.BuildError("its parsed feeds are not what its marker describes")
        return restore(store, snap, cache_dir)

    monkeypatch.setattr(build_module, "restore_snapshot", broken)

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED + timedelta(days=3))
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert read_pointer(world.store, AUSTRIA)[0].snapshot_id == later.snapshot_id
    assert world.store.get(correction_key(earlier)) is None
    assert "could not be loaded to count what its record lacks" in caplog.text
    assert tried == [earlier.snapshot_id]
    inputs = builder.gather(AUSTRIA, pointer=read_pointer(world.store, AUSTRIA)[0], retry=True)
    assert inputs.context.uncounted == ()
    assert [rival.snapshot_id for rival in Builder(world.store, fastf1=None, now=builder._now).gather(
        AUSTRIA, retry=True
    ).context.uncounted] == [earlier.snapshot_id]
