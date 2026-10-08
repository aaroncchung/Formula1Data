"""F1's mark for a pedal it has no reading of, read from its raw car feed.

The twenty-eighth review found a throttle of 104 in the archive, and the
answer to it took 104 for F1's mark for a sample with no pedal reading: the
throttle and the brake of such a sample were left without a value. The
twenty-ninth, before it was cut short, counted the raw feed and found the
mark in each pedal by itself too. A brake of 104 beside a real throttle is
941 samples inside laps in the 2026 Australian GP and 92,017 in the 2026
Hungarian GP, and FastF1 hands every one of them on as the brake on.

So a build reads the raw feed, which the archive keeps beside FastF1's cache
of it, and takes each pedal's mark from there.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import zlib
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
import requests
import requests_cache
import urllib3

from f1data.archive import HTTP_ARCHIVE, read_raw_response, write_snapshot
from f1data.artifacts import build_artifacts
from f1data.build import Builder
from f1data.carfeed import CAR_FEED, PedalMarks, parse_pedal_marks
from f1data.coverage import apply_classification, measure_coverage
from f1data.fetch import HTTP_CACHE_FILE
from f1data.publish import publish_session
from f1data.store import MemoryStore
from f1data.telemetry import extract_telemetry
from tests.building import FIRST_FETCH, Archive
from tests.fakes import make_session
from tests.race import IDENTITY, RACE_START_SECONDS, classification, extras, make_race
from tests.recorded import archive_store
from tests.test_archive import fetched_session
from tests.test_artifacts import read
from tests.test_build_inputs import SOON_AFTER
from tests.test_fifth_review import EVERYONE
from tests.test_publish import AUSTRIA
from tests.test_recorded_race import recorded

AUSTRALIA_2026 = 11234
HUNGARY_2026 = 11342
# The second lap of BBB in the stand-in race runs from 80.5 s to 161 s after the start.
STRETCH = (RACE_START_SECONDS + 100.0, RACE_START_SECONDS + 101.5)
ADDRESS = "https://livetiming.formula1.com/static/2026/2026-06-28_Ring_Grand_Prix/2026-06-28_Race/"


def car_feed_of(session, marked: dict[str, dict[str, tuple[float, float]]] | None = None, shift_ms: float = 0.0) -> bytes:
    """F1's car feed for a session, as F1 serves it, from the session's own table of it.

    ``marked`` gives, by car number and by pedal ("throttle" or "brake"), a
    stretch of session time in which F1 sends its mark for that pedal. The
    session's own table is changed to match what FastF1 would then have made
    of the feed: the throttle as sent, and the brake on.
    """
    marked = marked or {}
    lines = []
    numbers = list(session.car_data)
    rows = len(session.car_data[numbers[0]])
    for number, stretches in marked.items():
        frame = session.car_data[number]
        seconds = frame["SessionTime"].dt.total_seconds()
        for pedal, (start, end) in stretches.items():
            inside = (seconds >= start) & (seconds <= end)
            assert inside.sum() >= 4
            frame.loc[inside, "Throttle" if pedal == "throttle" else "Brake"] = 104.0 if pedal == "throttle" else True
    for row in range(rows):
        cars = {}
        for number in numbers:
            frame = session.car_data[number]
            seconds = frame["SessionTime"].iloc[row].total_seconds()
            stretches = marked.get(number, {})
            in_brake = "brake" in stretches and stretches["brake"][0] <= seconds <= stretches["brake"][1]
            cars[number] = {
                "Channels": {
                    "0": int(frame["RPM"].iloc[row]),
                    "2": int(frame["Speed"].iloc[row]),
                    "3": int(frame["nGear"].iloc[row]),
                    "4": int(frame["Throttle"].iloc[row]),
                    "5": 104 if in_brake else (100 if bool(frame["Brake"].iloc[row]) else 0),
                }
            }
        # One entry to a message, each car's sample at its own instant as F1
        # sends them: the stand-in's cars tick a few milliseconds apart, so a
        # message here is one car's.
        for number in numbers:
            moment = session.car_data[number]["Date"].iloc[row] + pd.Timedelta(milliseconds=shift_ms)
            entry = {"Utc": moment.strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z", "Cars": {number: cars[number]}}
            packed = zlib.compressobj(wbits=-zlib.MAX_WBITS)
            payload = packed.compress(json.dumps({"Entries": [entry]}).encode()) + packed.flush()
            lines.append(f'00:00:00.000"{base64.b64encode(payload).decode()}"')
    return ("\r\n".join(lines) + "\r\n").encode("utf-8-sig")


def lap_of(session, feed: bytes | None, code: str = "BBB", number: int = 2):
    return extract_telemetry(session, parse_pedal_marks(feed) if feed else None).laps[(code, number)]


def unknown(values) -> np.ndarray:
    return np.array([value is None for value in values])


def in_stretch(lap, stretch=STRETCH) -> np.ndarray:
    seconds = (lap.start_ms + lap.time_ms) / 1000
    return (seconds >= stretch[0]) & (seconds <= stretch[1])


# --- reading the feed ------------------------------------------------------------------


def test_the_feed_gives_each_cars_samples_and_which_pedals_are_marked():
    session = make_race()
    feed = car_feed_of(session, {"2": {"brake": STRETCH}, "3": {"throttle": STRETCH}})

    marks = parse_pedal_marks(feed)

    assert sorted(marks) == ["1", "2", "3"]
    for number, of_car in marks.items():
        frame = session.car_data[number]
        assert len(of_car.instants) == len(frame)
        assert (np.diff(of_car.instants) > 0).all()
        assert (of_car.instants == frame["Date"].to_numpy(dtype="datetime64[ns]").astype("int64")).all()
    seconds = session.car_data["2"]["SessionTime"].dt.total_seconds().to_numpy()
    inside = (seconds >= STRETCH[0]) & (seconds <= STRETCH[1])
    assert (marks["2"].brake == inside).all() and not marks["2"].throttle.any()
    assert (marks["3"].throttle == inside).all() and not marks["3"].brake.any()
    assert not marks["1"].brake.any() and not marks["1"].throttle.any()


def test_a_line_that_cannot_be_read_and_a_car_missing_a_channel_are_passed_over():
    session = make_race()
    whole = car_feed_of(session).decode("utf-8-sig").split("\r\n")
    partial = {"Entries": [{"Utc": "2026-06-28T12:00:00.1230000Z", "Cars": {"9": {"Channels": {"0": 1, "2": 2}}}}]}
    packed = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    without_a_brake = base64.b64encode(packed.compress(json.dumps(partial).encode()) + packed.flush()).decode()
    damaged = ['00:00:00.000"not base 64 at all"', "", f'00:00:00.000"{without_a_brake}"', '00:00:00.000"e30="', *whole]

    marks = parse_pedal_marks("\r\n".join(damaged).encode("utf-8-sig"))

    assert sorted(marks) == ["1", "2", "3"]
    assert len(marks["2"].instants) == len(session.car_data["2"])
    assert parse_pedal_marks(b"") == {} and parse_pedal_marks(b"\xef\xbb\xbfnothing here\r\n") == {}


def test_a_sample_is_found_a_millisecond_from_where_f1_sent_it_and_no_further():
    """FastF1 cuts a date to the microsecond and then rounds it to the millisecond.

    Twenty of the 31,179 samples of each car in the 2026 Australian GP are a
    millisecond apart in its table from the date F1 sent.
    """
    instants = np.array([1_000, 1_250, 1_500], dtype=np.int64) * 1_000_000
    marks = PedalMarks(instants=instants, throttle=np.array([False, True, False]), brake=np.array([True, False, False]))

    found, throttle, brake = marks.at(np.array([1_001, 1_249, 1_499, 1_375, 900], dtype=np.int64) * 1_000_000)

    assert found.tolist() == [True, True, True, False, False]
    assert throttle.tolist() == [False, True, False, False, False]
    assert brake.tolist() == [True, False, False, False, False]
    nothing = PedalMarks(instants=np.array([], dtype=np.int64), throttle=np.array([], dtype=bool), brake=np.array([], dtype=bool))
    assert nothing.at(instants)[0].tolist() == [False, False, False]


# --- each pedal by itself ----------------------------------------------------------------


def test_a_brake_f1_marks_by_itself_has_no_reading_and_the_throttle_beside_it_has():
    session = make_race()
    feed = car_feed_of(session, {"2": {"brake": STRETCH}})

    lap = lap_of(session, feed)
    inside = in_stretch(lap)

    assert inside.sum() >= 4 and unknown(lap.braking())[inside].all()
    assert lap.throttle_known is None and None not in lap.throttle()
    # FastF1's table has the brake on there, which is what was published.
    assert lap.brake[inside].all()
    # Outside the stretch the brake is what it was.
    plain = lap_of(make_race(), None)
    assert [value for value, there in zip(lap.braking(), ~inside) if there] == [
        value for value, there in zip(plain.braking(), ~inside) if there
    ]


def test_without_the_raw_feed_a_brake_marked_by_itself_cannot_be_told_from_braking():
    """Which is what the fix of the twenty-eighth round, on FastF1's table alone, left published."""
    session = make_race()
    car_feed_of(session, {"2": {"brake": STRETCH}})

    lap = lap_of(session, None)

    assert lap.brake_known is None and lap.brake[in_stretch(lap)].all()


def test_a_throttle_f1_marks_by_itself_has_no_reading_and_the_brake_beside_it_has():
    session = make_race()
    feed = car_feed_of(session, {"2": {"throttle": STRETCH}})

    lap = lap_of(session, feed)
    inside = in_stretch(lap)

    assert unknown(lap.throttle())[inside].all()
    assert lap.brake_known is None and None not in lap.braking()
    # Without the raw feed the brake there is taken to have no reading either:
    # the two marks come together for all but one such sample in seventy.
    assert unknown(lap_of(session, None).braking())[inside].all()


def test_both_pedals_marked_have_neither_and_other_cars_are_untouched():
    session = make_race()
    feed = car_feed_of(session, {"2": {"throttle": STRETCH, "brake": STRETCH}})

    lap = lap_of(session, feed)
    inside = in_stretch(lap)

    assert unknown(lap.throttle())[inside].all() and unknown(lap.braking())[inside].all()
    # A throttle is drawn between two samples, so it has no reading up to the
    # reading before the stretch; a brake is held from the sample before, so
    # it has one until the stretch begins.
    assert unknown(lap.braking()).sum() <= unknown(lap.throttle()).sum()
    assert not unknown(lap.braking())[~inside & ((lap.start_ms + lap.time_ms) / 1000 < STRETCH[0])].any()
    assert lap_of(session, feed, code="AAA").brake_known is None
    assert lap_of(session, feed, number=3).brake_known is None


# --- a raw feed that is not this session's -----------------------------------------------------


@pytest.mark.parametrize(
    ("why", "feed_of"),
    [
        # Every sample a quarter of a second from the table's.
        ("its samples are at other instants", lambda session: car_feed_of(make_race(), shift_ms=120.0)),
        # The same instants, and a throttle marked where the table has none.
        ("its throttle is marked elsewhere", lambda session: car_feed_of(make_race(), {"2": {"throttle": STRETCH}})),
    ],
)
def test_a_raw_feed_the_table_was_not_made_from_is_not_believed(why, feed_of, caplog):
    session = make_race()
    # The table says the brake is on through the stretch, and the raw feed
    # given is some other: nothing in it says that is a mark.
    seconds = session.car_data["2"]["SessionTime"].dt.total_seconds()
    session.car_data["2"].loc[(seconds >= STRETCH[0]) & (seconds <= STRETCH[1]), "Brake"] = True

    with caplog.at_level(logging.WARNING, logger="f1data.telemetry"):
        lap = lap_of(session, feed_of(session))

    assert lap.brake_known is None and lap.throttle_known is None, why
    assert "is not the one FastF1's table of car 2 was made from" in caplog.text


def test_a_car_the_raw_feed_does_not_have_is_read_from_the_table_alone():
    session = make_race()
    feed = car_feed_of(session)
    marks = parse_pedal_marks(feed)
    del marks["2"]

    lap = extract_telemetry(session, marks).laps[("BBB", 2)]

    assert lap.brake_known is None and lap.throttle_known is None


# --- from the archive to the build ---------------------------------------------------------------


class _Feeds(requests.adapters.BaseAdapter):
    """Answers F1's addresses from memory, so that no request leaves the machine."""

    def __init__(self, bodies: dict[str, tuple[int, bytes]]) -> None:
        super().__init__()
        self.bodies = bodies

    def send(self, request, **kwargs):
        status, body = self.bodies.get(request.url.split("?", 1)[0], (404, b"not found"))
        response = requests.Response()
        response.status_code = status
        response._content = body
        response.request = request
        response.url = request.url
        # What the cache copies a response's body from.
        response.raw = urllib3.HTTPResponse(
            body=io.BytesIO(body), status=status, headers={}, preload_content=False, request_url=request.url
        )
        return response

    def close(self):
        pass


def http_cache(cache_dir, bodies: dict[str, tuple[int, bytes]], keep: tuple[int, ...] = (200,)) -> None:
    """The HTTP cache FastF1 leaves behind, written by the library it uses and with its settings.

    ``keep`` is which answers are kept. FastF1 keeps a 200 and nothing else.
    """
    session = requests_cache.CachedSession(
        cache_name=str(cache_dir / "fastf1_http_cache"),
        backend="sqlite",
        allowable_methods=("GET", "POST"),
        allowable_codes=keep,
        expire_after=timedelta(hours=12),
        cache_control=True,
        stale_if_error=True,
    )
    session.mount("https://", _Feeds(bodies))
    for address in bodies:
        session.get(address)
    session.close()


def fetched_with(tmp_path, bodies: dict[str, tuple[int, bytes]], keep: tuple[int, ...] = (200,)):
    """A fetch whose raw responses are a real HTTP cache holding ``bodies``."""
    fetched = fetched_session(tmp_path)
    (fetched.cache_dir / HTTP_CACHE_FILE).unlink()
    http_cache(fetched.cache_dir, bodies, keep)
    assert (fetched.cache_dir / HTTP_CACHE_FILE).is_file()
    return fetched


def archived(tmp_path, bodies: dict[str, tuple[int, bytes]], keep: tuple[int, ...] = (200,)):
    store = MemoryStore()
    return store, write_snapshot(store, fetched_with(tmp_path, bodies, keep))


def test_the_car_feed_is_read_back_out_of_the_raw_responses_kept_with_a_snapshot(tmp_path):
    feed = car_feed_of(make_race(), {"2": {"brake": STRETCH}})
    store, snapshot = archived(
        tmp_path,
        {
            f"{ADDRESS}SessionInfo.jsonStream": (200, b"session info"),
            f"{ADDRESS}{CAR_FEED}": (200, feed),
            f"{ADDRESS}Position.z.jsonStream": (200, b"positions"),
        },
    )

    assert read_raw_response(store, snapshot, CAR_FEED) == feed
    assert read_raw_response(store, snapshot, "Position.z.jsonStream") == b"positions"
    assert read_raw_response(store, snapshot, "WeatherData.jsonStream") is None
    # Not a name that another's ends with.
    assert read_raw_response(store, snapshot, "z.jsonStream") is None


def test_a_refusal_kept_under_the_feeds_name_is_not_the_feed(tmp_path):
    """FastF1 keeps no answer but a 200. Should a cache ever hold another, it is not F1's feed."""
    refusal = {f"{ADDRESS}{CAR_FEED}": (403, b"<html>Access denied</html>")}
    store, snapshot = archived(tmp_path, refusal, keep=(200, 403))

    assert read_raw_response(store, snapshot, CAR_FEED) is None


def test_of_two_answers_under_the_feeds_name_the_fuller_is_the_feed(tmp_path):
    """FastF1 asks a mirror when F1 refuses, so a cache can hold the feed under two addresses."""
    mirror = "https://livetiming-mirror.fastf1.dev/static/2026/2026-06-28_Ring_Grand_Prix/2026-06-28_Race/"
    feed = car_feed_of(make_race())
    for order in ((ADDRESS, mirror), (mirror, ADDRESS)):
        bodies = {f"{order[0]}{CAR_FEED}": (200, feed[: len(feed) // 2]), f"{order[1]}{CAR_FEED}": (200, feed)}
        store, snapshot = archived(tmp_path / order[0].split("/")[2], bodies)

        assert read_raw_response(store, snapshot, CAR_FEED) == feed


def test_a_build_is_given_the_car_feed_of_the_snapshot_it_builds(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    feed = car_feed_of(make_race())
    fetched = fetched_with(tmp_path, {f"{ADDRESS}{CAR_FEED}": (200, feed)})
    written = write_snapshot(world.store, fetched, now=FIRST_FETCH)
    world.feeds[written.snapshot_id] = make_session()
    builder = Builder(world.store, fastf1=None, now=lambda: SOON_AFTER)

    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert world.car_feeds == [feed]


def test_a_build_of_a_snapshot_whose_raw_responses_cannot_be_read_is_made_without_them(tmp_path, monkeypatch):
    world = Archive(monkeypatch, EVERYONE)
    world.snapshot(tmp_path)
    builder = Builder(world.store, fastf1=None, now=lambda: SOON_AFTER)

    outcome = publish_session(world.store, AUSTRIA, builder.gather, builder.build)

    assert outcome.action == "published"
    assert world.car_feeds == [None]


def test_raw_responses_that_are_not_a_table_of_them_give_nothing_and_say_so(tmp_path, caplog):
    store = MemoryStore()
    snapshot = write_snapshot(store, fetched_session(tmp_path))

    with caplog.at_level(logging.WARNING, logger="f1data.archive"):
        assert read_raw_response(store, snapshot, CAR_FEED) is None

    assert "cannot be read as the responses FastF1 kept" in caplog.text


def test_a_snapshot_with_no_raw_responses_gives_nothing(tmp_path):
    fetched = fetched_session(tmp_path)
    (fetched.cache_dir / HTTP_CACHE_FILE).unlink()
    store = MemoryStore()
    snapshot = write_snapshot(store, fetched)

    assert HTTP_ARCHIVE not in snapshot.objects
    assert read_raw_response(store, snapshot, CAR_FEED) is None


def test_a_build_given_the_raw_feed_publishes_no_brake_where_f1_had_none():
    session = make_race()
    feed = car_feed_of(session, {"2": {"brake": STRETCH}})
    found = extras()
    result = classification()
    measurement = apply_classification(measure_coverage(session, "R", found), result.laps_by_number)

    with_it = build_artifacts(session, IDENTITY, result, found, measurement, feed)
    without = build_artifacts(session, IDENTITY, result, found, measurement)

    def lap_two(files):
        return next(lap for lap in read(files, "telemetry/BBB.json")["laps"] if lap["lap_number"] == 2)

    assert None in lap_two(with_it)["brake"] and None not in lap_two(with_it)["throttle_pct"]
    assert None not in lap_two(without)["brake"]
    changed = sorted(path for path in with_it if with_it[path] != without[path])
    assert "telemetry/BBB.json" in changed and "telemetry/AAA.json" not in changed


# --- the races it was found in ------------------------------------------------------------------


def test_the_archives_raw_feed_is_the_one_each_sessions_table_was_made_from(tmp_path, caplog):
    """The 2026 Australian GP: every sample of every car is in the raw feed, with the throttle marked where the table has it."""
    session, _, snapshot = recorded(tmp_path, AUSTRALIA_2026)
    store = archive_store()
    feed = read_raw_response(store, snapshot, CAR_FEED)

    marks = parse_pedal_marks(feed)
    with caplog.at_level(logging.WARNING, logger="f1data.telemetry"):
        telemetry = extract_telemetry(session, marks)

    assert "is not the one FastF1's table" not in caplog.text
    assert len(marks) == 22 and all(len(of_car.instants) == 31_179 for of_car in marks.values())
    # 90,090 samples with both pedals marked, 13 with the throttle alone, 1,584 with the brake alone.
    both = sum(int((of_car.throttle & of_car.brake).sum()) for of_car in marks.values())
    throttle_alone = sum(int((of_car.throttle & ~of_car.brake).sum()) for of_car in marks.values())
    brake_alone = sum(int((~of_car.throttle & of_car.brake).sum()) for of_car in marks.values())
    assert (both, throttle_alone, brake_alone) == (90_090, 13, 1_584)
    # And with the raw feed, more of the brake is known to be no reading than without it.
    plain = extract_telemetry(session)
    with_marks = sum(int(unknown(lap.braking()).sum()) for lap in telemetry.laps.values())
    from_the_table = sum(int(unknown(lap.braking()).sum()) for lap in plain.laps.values())
    assert with_marks > from_the_table > 0


def test_the_2026_hungarian_gps_brake_is_mostly_no_reading_and_is_not_published_as_braking(tmp_path, caplog):
    session, _, snapshot = recorded(tmp_path, HUNGARY_2026)
    feed = read_raw_response(archive_store(), snapshot, CAR_FEED)

    with caplog.at_level(logging.WARNING, logger="f1data.telemetry"):
        telemetry = extract_telemetry(session, parse_pedal_marks(feed))
    plain = extract_telemetry(session)

    assert "is not the one FastF1's table" not in caplog.text
    samples = sum(lap.sample_count for lap in telemetry.laps.values())
    no_reading = sum(int(unknown(lap.braking()).sum()) for lap in telemetry.laps.values())
    by_the_table_alone = sum(int(unknown(lap.braking()).sum()) for lap in plain.laps.values())
    said_to_be_braking = sum(int(np.asarray(lap.brake, dtype=bool).sum()) for lap in plain.laps.values())
    known_to_be_braking = sum(sum(value is True for value in lap.braking()) for lap in telemetry.laps.values())
    # More than a quarter of the race has no brake reading, and FastF1's
    # table alone shows less than a third of that.
    assert (samples, no_reading, by_the_table_alone) == (938_006, 267_618, 83_511)
    # The brake was on for 47% of the race as FastF1 hands it on, and is on
    # for 26% of the samples that have a reading.
    assert round(100 * said_to_be_braking / samples, 1) == 47.1
    assert round(100 * known_to_be_braking / (samples - no_reading), 1) == 25.9
