"""The case the thirty-eighth review of this code found (a comment on pull request 11, 2026-10-12, at a79f061).

One finding, of the second rank, in what round thirty-five added. The laps on
which a feed repeats itself are counted and are a bar, and the order in which
a build picks a snapshot did not read the count. Two snapshots with the same
driver short on that bar, one with three such laps and one with forty, had as
many shortfalls and the same weakest share, since a lap that repeats itself
arrived on time and is "usable": the later fetch won, however much worse.

A lap a feed repeats itself on is now taken off the feed's usable laps where
the weakest share is worked out, and between two snapshots that still tie the
one with fewer such laps over every driver wins, before the later fetch does.
"""

from __future__ import annotations

from f1data.archive import select_snapshot
from f1data.coverage import CAR_REPEATS_BAR, POSITION_REPEATS_BAR, repeating_laps, weakest_share
from tests.fakes import LAP_SECONDS, RACE_START, make_session
from tests.test_publish import snapshot
from tests.test_thirty_fifth_review import (
    before_repeats_were_counted,
    car_feed_repeats,
    position_feed_repeats,
    shortfalls,
)

EARLIER, LATER = "20261005T200000Z-aaaaaaaa", "20261006T200000Z-bbbbbbbb"


def repeats(car: dict[str, range] | None = None, position: dict[str, range] | None = None):
    session = make_session()
    for number, laps in (car or {}).items():
        car_feed_repeats(session, number, laps=laps)
    for number, laps in (position or {}).items():
        position_feed_repeats(session, number, laps=laps)
    return session


def figures(snap, code: str = "AAA") -> tuple[int, int, int, int]:
    driver = snap.coverage["drivers"][code]
    return (
        driver["car_laps"],
        driver["position_laps"],
        driver["car_repeating_laps"],
        driver["position_repeating_laps"],
    )


def test_a_retry_whose_car_feed_repeats_itself_on_more_laps_does_not_win():
    """Every lap of both has car data, and the same driver is short on the
    same bar. Nothing but the time of the fetch told them apart."""
    earlier = snapshot(snapshot_id=EARLIER, session=repeats(car={"1": range(10, 11)}))
    later = snapshot(snapshot_id=LATER, session=repeats(car={"1": range(3, 11)}))
    assert figures(earlier) == (10, 10, 1, 0) and figures(later) == (10, 10, 8, 0)
    assert shortfalls(earlier.coverage) == shortfalls(later.coverage) == {(CAR_REPEATS_BAR, "AAA")}

    assert select_snapshot([earlier, later]) == earlier
    assert select_snapshot([later, earlier]) == earlier


def test_nor_one_whose_position_feed_does():
    earlier = snapshot(snapshot_id=EARLIER, session=repeats(position={"1": range(10, 11)}))
    later = snapshot(snapshot_id=LATER, session=repeats(position={"1": range(3, 11)}))
    assert figures(earlier) == (10, 10, 0, 1) and figures(later) == (10, 10, 0, 8)
    assert shortfalls(earlier.coverage) == shortfalls(later.coverage) == {(POSITION_REPEATS_BAR, "AAA")}

    assert (weakest_share(earlier.coverage), weakest_share(later.coverage)) == (0.9, 0.2)
    assert select_snapshot([later, earlier]) == earlier


def test_a_lap_that_repeats_itself_is_not_a_usable_one():
    """The weakest share counted it as one. A fetch with eight of a driver's
    ten laps repeating stood above one with four of them missing."""
    session = make_session()
    car = session.car_data["1"]
    session.car_data["1"] = car[car["SessionTime"].dt.total_seconds() < RACE_START + 6 * LAP_SECONDS]
    six_of_ten = snapshot(snapshot_id=EARLIER, session=session)
    two_of_ten = snapshot(snapshot_id=LATER, session=repeats(car={"1": range(3, 11)}))
    assert len(six_of_ten.shortfalls()) == len(two_of_ten.shortfalls()) == 1

    assert weakest_share(six_of_ten.coverage) == 0.6
    assert weakest_share(two_of_ten.coverage) == 0.2
    assert select_snapshot([two_of_ten, six_of_ten]) == six_of_ten


def test_the_laps_that_repeat_are_counted_over_every_driver():
    """The weakest share is one driver's on one feed. With a driver whose
    feed repeats itself on nine laps in both fetches, it says nothing of
    another whose feed does on one lap in the first and on eight in the next."""
    earlier = snapshot(snapshot_id=EARLIER, session=repeats(car={"1": range(10, 11), "2": range(2, 11)}))
    later = snapshot(snapshot_id=LATER, session=repeats(car={"1": range(3, 11), "2": range(2, 11)}))
    assert shortfalls(earlier.coverage) == shortfalls(later.coverage)
    assert weakest_share(earlier.coverage) == weakest_share(later.coverage) == 0.1
    assert (repeating_laps(earlier.coverage), repeating_laps(later.coverage)) == (10, 17)

    assert select_snapshot([later, earlier]) == earlier


def test_a_retry_that_does_no_worse_still_wins():
    earlier = snapshot(snapshot_id=EARLIER, session=repeats(car={"1": range(3, 11)}))
    same = snapshot(snapshot_id=LATER, session=repeats(car={"1": range(3, 11)}))
    better = snapshot(snapshot_id=LATER, session=repeats(car={"1": range(10, 11)}))

    assert select_snapshot([earlier, same]) == same
    assert select_snapshot([earlier, better]) == better


def test_a_record_from_before_the_laps_were_counted_takes_nothing_off():
    """A count that is absent was never taken. The build that reads such a
    snapshot counts it and decides again."""
    counted = snapshot(session=repeats(car={"1": range(3, 11)})).coverage
    never = before_repeats_were_counted(counted)

    assert (weakest_share(counted), repeating_laps(counted)) == (0.2, 8)
    assert (weakest_share(never), repeating_laps(never)) == (1.0, 0)
