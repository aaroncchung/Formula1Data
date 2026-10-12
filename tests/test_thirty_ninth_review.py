"""The cases the thirty-ninth review of this code found (a comment on pull request 11, 2026-10-12, at c23644f).

Two findings, of the second rank, both in the order the round before gave
the choice between two snapshots.

After the weakest share it read how many laps repeat themselves, over every
driver, and nothing of how many laps each driver has. A retry that brought a
driver two laps more and one that repeats lost to the fetch before it.

And a lap that repeats itself was taken off the feed's usable laps whether
or not it was one of them. A lap with a hole in it is not usable, and one
that repeats itself as well was taken off twice: a retry with one lap more,
two of whose bad laps were bad both ways, stood below the fetch before it.

A measurement now counts the laps a feed can be relied on for, those with no
hole in them that do not repeat themselves. The weakest share is worked out
from those, and two snapshots it cannot tell apart are ordered by the same
share over every driver and feed before the laps that repeat are counted.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from f1data import layout
from f1data.archive import list_snapshots, select_snapshot, write_snapshot
from f1data.build import Builder
from f1data.coverage import (
    apply_classification,
    evaluate_coverage,
    is_measurement,
    overall_share,
    repeating_laps,
    weakest_share,
)
from f1data.publish import publish_session, read_pointer
from tests.building import Archive
from tests.fakes import LAP_SECONDS, RACE_START, make_session, measure
from tests.test_archive import fetched_session
from tests.test_fifth_review import WINDOW_CLOSED, correction
from tests.test_publish import AUSTRIA, snapshot
from tests.test_thirty_eighth_review import EARLIER, LATER
from tests.test_thirty_fifth_review import car_feed_repeats, position_feed_repeats, shortfalls

LAPS = 40
EVERYONE = {"1": LAPS, "2": LAPS, "3": LAPS}
RELIABLE = ("car_reliable_laps", "position_reliable_laps")


def hole(session, feed: str, number: str, laps) -> None:
    """Ten seconds of a feed gone from the middle of each of ``laps``, counted from 1."""
    telemetry = getattr(session, feed)[number]
    seconds = telemetry["SessionTime"].dt.total_seconds()
    gone = seconds < 0
    for lap in laps:
        start = RACE_START + (lap - 1) * LAP_SECONDS + 30.0
        gone |= (seconds >= start) & (seconds < start + 10.0)
    getattr(session, feed)[number] = telemetry[~gone].reset_index(drop=True)


def race(car_holes=None, car_repeats=None, position_holes=None, position_repeats=None):
    """Forty laps each, in which two may be missing and two may repeat."""
    session = make_session(laps_per_driver=LAPS)
    for number, laps in (car_repeats or {}).items():
        car_feed_repeats(session, number, laps=laps)
    for number, laps in (position_repeats or {}).items():
        position_feed_repeats(session, number, laps=laps)
    for number, laps in (car_holes or {}).items():
        hole(session, "car_data", number, laps)
    for number, laps in (position_holes or {}).items():
        hole(session, "pos_data", number, laps)
    return session


def car_figures(measurement, code: str = "AAA") -> tuple[int, int, int]:
    driver = measurement["drivers"][code]
    return driver["car_laps"], driver["car_repeating_laps"], driver["car_reliable_laps"]


def position_figures(measurement, code: str = "AAA") -> tuple[int, int, int]:
    driver = measurement["drivers"][code]
    return driver["position_laps"], driver["position_repeating_laps"], driver["position_reliable_laps"]


def before_reliable_laps_were_counted(measurement: dict) -> dict:
    """A measurement as the round before recorded it: the laps that repeat, and not which."""
    return {
        **measurement,
        "drivers": {
            code: {key: value for key, value in driver.items() if key not in RELIABLE}
            for code, driver in measurement["drivers"].items()
        },
    }


# --- 2: a lap with a hole in it that repeats itself is one lap ---------------------


def test_a_lap_with_a_hole_in_it_that_repeats_itself_is_counted_once():
    """Laps 5 to 7 have a hole in them, and 6 and 7 repeat themselves too.
    Thirty-seven laps are sound, and 37 less 2 was what stood."""
    measurement = measure(race(car_holes={"1": [5, 6, 7]}, car_repeats={"1": [6, 7]}))

    assert car_figures(measurement) == (37, 2, 37)
    assert weakest_share(measurement) == 37 / 40


def test_a_lap_that_only_repeats_itself_is_still_taken_off():
    measurement = measure(race(car_holes={"1": [5]}, car_repeats={"1": [6, 7]}))

    assert car_figures(measurement) == (39, 2, 37)
    assert weakest_share(measurement) == 37 / 40


def test_the_position_feed_is_counted_the_same_way():
    measurement = measure(race(position_holes={"2": [5, 6, 7]}, position_repeats={"2": [6, 7, 8]}))

    assert position_figures(measurement, "BBB") == (37, 3, 36)
    assert car_figures(measurement, "BBB") == (40, 0, 40)
    assert weakest_share(measurement) == 36 / 40


def test_a_retry_with_a_lap_more_wins_though_two_of_its_bad_laps_are_bad_both_ways():
    """The finding. Both are short of car data for the one driver, and the
    two laps that repeat are as many as may. The earlier has 36 laps to rely
    on and the later 37, and the later stood at 35."""
    earlier = snapshot(snapshot_id=EARLIER, session=race(car_holes={"1": [5, 6, 7, 8]}))
    later = snapshot(snapshot_id=LATER, session=race(car_holes={"1": [5, 6, 7]}, car_repeats={"1": [6, 7]}))
    assert car_figures(earlier.coverage) == (36, 0, 36) and car_figures(later.coverage) == (37, 2, 37)
    assert shortfalls(earlier.coverage) == shortfalls(later.coverage) == {("car_data", "AAA")}

    assert (weakest_share(earlier.coverage), weakest_share(later.coverage)) == (36 / 40, 37 / 40)
    assert select_snapshot([earlier, later]) == later
    assert select_snapshot([later, earlier]) == later


def test_a_record_that_does_not_say_which_laps_repeat_has_them_all_taken_off():
    """The round before counted the laps that repeat and not how many of
    them have a hole in them too. Too few is the side to be wrong on, until
    a build counts them."""
    counted = measure(race(car_holes={"1": [5, 6, 7]}, car_repeats={"1": [6, 7]}))
    older = before_reliable_laps_were_counted(counted)

    assert is_measurement(older) and evaluate_coverage(older) == evaluate_coverage(counted)
    assert (weakest_share(counted), weakest_share(older)) == (37 / 40, 35 / 40)


def test_a_driver_known_from_the_result_alone_has_no_laps_to_rely_on():
    judged = apply_classification(measure(race()), {**EVERYONE, "4": LAPS})

    assert [judged["drivers"]["#4"][key] for key in RELIABLE] == [0, 0]
    assert is_measurement(judged) and weakest_share(judged) == 0.0


@pytest.mark.parametrize("value", ["37", 37.0, -1, True])
def test_a_count_of_laps_to_rely_on_is_a_count_or_the_record_is_not_a_measurement(value):
    measurement = measure(race())
    measurement["drivers"]["AAA"]["car_reliable_laps"] = value

    assert not is_measurement(measurement)


def test_a_build_counts_the_laps_to_rely_on_for_a_snapshot_whose_record_does_not_have_them(tmp_path, monkeypatch):
    """No session is fetched again for this. The build of this pipeline
    version counts them from the feeds it has loaded, writes them beside the
    snapshot and decides again, as it did for the laps that repeat."""
    world = Archive(monkeypatch, EVERYONE)
    session = race(car_holes={"1": [5, 6, 7]}, car_repeats={"1": [6, 7]})
    fetched = fetched_session(tmp_path, session)
    written = write_snapshot(
        world.store, replace(fetched, coverage=before_reliable_laps_were_counted(fetched.coverage)), now=WINDOW_CLOSED
    )
    world.feeds[written.snapshot_id] = session
    (listed,) = list_snapshots(world.store)
    assert weakest_share(listed.judged_against(EVERYONE).coverage) == 35 / 40

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED + timedelta(days=3))
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert [(item["bar"], item["driver"]) for item in read_pointer(world.store, AUSTRIA)[0].shortfalls] == [
        ("car_data", "AAA")
    ]
    corrected = correction(world.store, written)
    assert corrected["pipeline_version"] == layout.PIPELINE_VERSION == 26
    assert car_figures(corrected["coverage"]) == (37, 2, 37)
    (listed,) = list_snapshots(world.store)
    assert weakest_share(listed.judged_against(EVERYONE).coverage) == 37 / 40


# --- 1: how the rest fared is how many laps they have, before how many repeat ------


def test_a_retry_that_brings_another_driver_more_laps_wins_though_one_of_them_repeats():
    """The finding. Driver 1 has half the car data in both, which is the
    weakest share of both. Driver 2 has 38 laps and then 40, one of which
    repeats itself: 39 to rely on. The earlier won for its one lap fewer
    that repeats."""
    half = range(21, 41)
    earlier = snapshot(snapshot_id=EARLIER, session=race(car_holes={"1": half, "2": [5, 6]}))
    later = snapshot(snapshot_id=LATER, session=race(car_holes={"1": half}, car_repeats={"2": [9]}))
    assert car_figures(earlier.coverage, "BBB") == (38, 0, 38) and car_figures(later.coverage, "BBB") == (40, 1, 39)
    assert shortfalls(earlier.coverage) == shortfalls(later.coverage) == {("car_data", "AAA")}
    assert weakest_share(earlier.coverage) == weakest_share(later.coverage) == 0.5
    assert (repeating_laps(earlier.coverage), repeating_laps(later.coverage)) == (0, 1)

    # Four feeds for each of three drivers: 480 laps, less driver 1's twenty and driver 2's.
    assert (overall_share(earlier.coverage), overall_share(later.coverage)) == (458 / 480, 459 / 480)
    assert select_snapshot([earlier, later]) == later
    assert select_snapshot([later, earlier]) == later


def test_with_as_many_laps_to_rely_on_the_one_with_fewer_that_repeat_wins():
    """A lap that is missing says so, and one that repeats itself does not."""
    half = range(21, 41)
    earlier = snapshot(snapshot_id=EARLIER, session=race(car_holes={"1": half, "2": [5, 6]}))
    later = snapshot(snapshot_id=LATER, session=race(car_holes={"1": half}, car_repeats={"2": [9, 10]}))
    assert shortfalls(earlier.coverage) == shortfalls(later.coverage)
    assert overall_share(earlier.coverage) == overall_share(later.coverage) == 458 / 480

    assert select_snapshot([earlier, later]) == earlier
    assert select_snapshot([later, earlier]) == earlier


def test_a_retry_that_is_the_same_still_wins():
    half = range(21, 41)
    earlier = snapshot(snapshot_id=EARLIER, session=race(car_holes={"1": half}, car_repeats={"2": [9]}))
    later = snapshot(snapshot_id=LATER, session=race(car_holes={"1": half}, car_repeats={"2": [9]}))

    assert select_snapshot([earlier, later]) == later
    assert select_snapshot([later, earlier]) == later


def test_a_session_with_no_laps_expected_of_anyone_has_nothing_short():
    measurement = measure(make_session())
    nobody = apply_classification(measurement, {})

    assert (weakest_share(nobody), overall_share(nobody)) == (1.0, 1.0)
