"""The cases the thirty-sixth review of this code found (a comment on pull request 11, 2026-10-12, at 212536b).

Three findings, each in what the round before had added. A car feed that
stops at a speed no moving car has was taken at its word, that the car was
standing, and none of its samples was judged; nor were the position feed's
beside it. The check on the fetch job read a run written down as finishing
in the future as one that had just finished. And the golden file of the
Austrian race had not been recorded again, by a suite the hosted tests do
not run.

Whether a car is moving is now also the position feed's to say, and the
timing's: a lap has room for standing only in what it took beyond the fastest
lap of the session. Over the nine races of 2026 from Australia to Britain
(10,406 laps) that changes no count, and no lap has a car standing for longer
than the lap had room for.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from f1data import layout
from f1data.archive import dump_json, write_snapshot
from f1data.build import Builder
from f1data.coverage import CAR_REPEATS_BAR, POSITION_REPEATS_BAR, STANDING_MARGIN_SECONDS
from f1data.policy import CLOCK_TOLERANCE, RUN_IS_OVERDUE_AFTER
from f1data.publish import publish_session, read_pointer
from tests.building import Archive
from tests.fakes import LAP_SECONDS, make_session, measure, run_laps_together
from tests.test_archive import fetched_session
from tests.test_fifteenth_review import job  # noqa: F401  (a fixture)
from tests.test_fifth_review import WINDOW_CLOSED, correction
from tests.test_publish import AUSTRIA
from tests.test_thirty_fifth_review import EVERYONE, lap_rows, position_feed_repeats, shortfalls

# --- 1: a feed that stops with the car "standing" ---------------------------------


def car_feed_stops(session, number: str, laps, speed: float = 0.0, share: float = 1.0) -> None:
    """The car feed sends one sample again and again, and its speed is one no moving car has."""
    car = session.car_data[number]
    for lap in laps:
        car.loc[lap_rows(car, lap, share), ["Speed", "RPM"]] = [speed, 4000.0]


def repeating(session, code: str = "AAA") -> tuple[int, int]:
    driver = measure(session)["drivers"][code]
    return driver["car_repeating_laps"], driver["position_repeating_laps"]


@pytest.mark.parametrize("speed", [0.0, 30.0])
def test_a_car_feed_that_stops_at_no_speed_is_not_a_car_that_is_standing(speed):
    """Whether the car was moving was read from the feed being judged. One
    that sent a speed of nought from lap 3 on said the car stood for eight
    laps, each of them timed at a lap's length, and was not judged at all."""
    session = make_session()
    car_feed_stops(session, "1", laps=range(3, 11), speed=speed)

    measurement = measure(session)

    driver = measurement["drivers"]["AAA"]
    assert (driver["car_laps"], driver["car_repeating_laps"], driver["position_repeating_laps"]) == (10, 8, 0)
    assert measurement["drivers"]["BBB"]["car_repeating_laps"] == 0
    assert shortfalls(measurement) == {(CAR_REPEATS_BAR, "AAA")}
    # What a fetch writes down of it is plain JSON.
    assert json.loads(json.dumps(measurement))["drivers"]["AAA"]["car_repeating_laps"] == 8


def test_both_feeds_stopped_together_are_judged_by_what_the_laps_took():
    """Neither feed has the car moving, and the timing has it round eight
    times. The position feed was judged where the car feed had the car
    moving, so it went unjudged with it."""
    session = make_session()
    car_feed_stops(session, "1", laps=range(3, 11))
    position_feed_repeats(session, "1", laps=range(3, 11))

    measurement = measure(session)

    assert repeating(session) == (8, 8)
    assert shortfalls(measurement) == {(CAR_REPEATS_BAR, "AAA"), (POSITION_REPEATS_BAR, "AAA")}


def test_the_position_feed_says_the_car_is_moving_on_a_lap_that_had_room_to_stand_in():
    """A lap three laps long, as behind a safety car, has room for the car to
    have stood for the 80 s its car feed says it did. The position feed has
    it going round all the while."""
    session = make_session()
    run_laps_together(session, "1", 3, 5)
    car_feed_stops(session, "1", laps=[3])

    assert repeating(session) == (1, 0)

    # Without the position feed nothing says otherwise, and the bar on
    # positions says what is wrong.
    session.pos_data["1"] = session.pos_data["1"].iloc[0:0]
    measurement = measure(session)
    assert measurement["drivers"]["AAA"]["car_repeating_laps"] == 0
    assert ("position", "AAA") in shortfalls(measurement)


@pytest.mark.parametrize(("share", "counted"), [(0.25, 0), (0.35, 1)])
def test_a_lap_with_no_room_repeats_itself_when_more_than_a_quarter_of_it_stood(share, counted):
    """A lap at the session's fastest has room for the margin and no more:
    the standing beyond it is judged, and the rest of the lap with it."""
    assert STANDING_MARGIN_SECONDS < 0.25 * LAP_SECONDS
    session = make_session()
    car_feed_stops(session, "1", laps=[5], share=share)
    position_feed_repeats(session, "1", laps=[5], share=share)

    assert repeating(session) == (counted, counted)


def test_a_car_stopped_in_its_pit_box_for_as_long_as_its_lap_was_slow_is_left_alone():
    """Half a minute in the box on a lap half a minute slow: every sample of
    it repeats, truthfully. Had the lap been no slower, it was not stood."""
    session = make_session()
    start = session.laps["LapStartTime"] + pd.Timedelta(seconds=30)
    later = (session.laps["DriverNumber"] == "1") & (session.laps["LapNumber"] > 5)
    slow = (session.laps["DriverNumber"] == "1") & (session.laps["LapNumber"] >= 5)
    session.laps.loc[later, "LapStartTime"] = start[later]
    session.laps.loc[slow, "Time"] = session.laps.loc[slow, "Time"] + pd.Timedelta(seconds=30)
    for feed, channels in ((session.car_data["1"], ["Speed", "RPM"]), (session.pos_data["1"], ["X", "Y"])):
        stopped = lap_rows(feed, 5, share=30 / LAP_SECONDS)
        feed.loc[stopped, channels] = [0.0, 4000.0] if channels[0] == "Speed" else feed.loc[stopped, channels].iloc[0].to_list()

    measurement = measure(session)

    assert repeating(session) == (0, 0)
    assert not {bar for bar, _ in shortfalls(measurement)} & {CAR_REPEATS_BAR, POSITION_REPEATS_BAR}


def test_a_session_with_no_lap_timed_at_both_ends_has_no_fastest_lap_and_is_measured_all_the_same():
    session = make_session()
    car_feed_stops(session, "1", laps=range(3, 11))
    session.laps["LapStartTime"] = pd.to_timedelta([pd.NaT] * len(session.laps))

    assert repeating(session) == (0, 0)


def test_a_record_that_took_a_stopped_feed_at_its_word_is_corrected_by_the_build(tmp_path, monkeypatch):
    """Every session in the archive was counted by the round before, or by
    none. A build counts again from the feeds it has loaded, as it did
    then."""
    world = Archive(monkeypatch, EVERYONE)
    session = make_session()
    car_feed_stops(session, "1", laps=range(3, 11))
    fetched = fetched_session(tmp_path, session)
    taken_at_its_word = json.loads(json.dumps(fetched.coverage))
    taken_at_its_word["drivers"]["AAA"]["car_repeating_laps"] = 0
    written = write_snapshot(world.store, replace(fetched, coverage=taken_at_its_word), now=WINDOW_CLOSED)
    world.feeds[written.snapshot_id] = session

    builder = Builder(world.store, fastf1=None, now=lambda: WINDOW_CLOSED + timedelta(days=3))
    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    pointer = read_pointer(world.store, AUSTRIA)[0]
    assert pointer.complete is False
    assert [(item["bar"], item["driver"]) for item in pointer.shortfalls] == [(CAR_REPEATS_BAR, "AAA")]
    assert correction(world.store, written)["coverage"]["drivers"]["AAA"]["car_repeating_laps"] == 8


# --- 2: a run that has not finished yet has not finished -----------------------------


def write_down(job, finished: datetime) -> None:  # noqa: F811  (the fixture's name)
    stamp = finished.strftime("%Y-%m-%dT%H:%M:%SZ")
    job.store.put(
        layout.LAST_RUN_KEY,
        dump_json({"started_at": stamp, "finished_at": stamp, "exit_code": 0, "failed_runs": 0, "host": "home"}),
    )


def test_a_run_written_down_as_finishing_tomorrow_vouches_for_nothing(job):  # noqa: F811
    """The machine that fetches stamps the record with its own clock. Set a
    day ahead, it wrote a time that was "-24.0 hours ago" until the day came
    round, and for that long the check passed with the job stopped."""
    assert RUN_IS_OVERDUE_AFTER < timedelta(days=1)
    write_down(job, datetime.now(timezone.utc) + timedelta(days=1))

    output, code = job.run("last-run", "--store", "x")

    assert code == 1 and "24.0 hours from now" in output
    assert "The clock that wrote that was wrong" in output and "hours ago" not in output
    # However late a run is allowed to be.
    assert job.run("last-run", "--store", "x", "--max-age-hours", "1000")[1] == 1


def test_a_clock_a_little_ahead_of_this_one_is_a_clock(job):  # noqa: F811
    now = datetime.now(timezone.utc)

    write_down(job, now + CLOCK_TOLERANCE - timedelta(minutes=5))
    output, code = job.run("last-run", "--store", "x")
    assert code == 0 and "with exit code 0." in output

    write_down(job, now + CLOCK_TOLERANCE + timedelta(minutes=5))
    assert job.run("last-run", "--store", "x")[1] == 1
