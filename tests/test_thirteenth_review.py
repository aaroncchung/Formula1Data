"""The cases the thirteenth review of this code found (GPT-6.1 Sol, 2026-10-06, at 4a1944d).

It was asked to rate by what F1's feeds have been seen to do, and to check
that the artifacts of one generation agree with each other on eight real
sessions. They do, but for one number: the count of stops F1's pit-stop feed
vouches for, which in the 2025 Canadian GP was 62 beside 33 stops, because F1
sends most of that race's stops twice. One finding is a path, not a form: a
new fetch could archive a session's weather without the feed's own lines and
be built with FastF1's zeros. Three are forms F1 has not been seen to send.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from f1data import normalize
from f1data.coverage import measure_coverage
from f1data.extras import (
    PIT_STOP_SERIES,
    WEATHER_SERIES,
    fetch_extras,
    parse_pit_stop_series,
    weather_lines_are_kept,
    weather_readings_sent,
)
from f1data.loaded import driver_codes
from f1data.models import artifact_json
from tests.race import extras, make_race
from tests.test_artifacts import built, read
from tests.test_extras import ARCHIVE_PATH, session
from tests.test_twelfth_review import pit_line, stop, weather_as_fastf1_parses

# --- R13-1: a stop F1 sends twice is one stop ------------------------------------

# The first four lines of the 2025 Canadian GP's pit-stop feed, as F1 sent them.
CANADA = (
    b'\xef\xbb\xbf01:13:41.760{"PitTimes":{"1":[{"Timestamp":"2025-06-15T18:18:46.814Z","PitStop":'
    b'{"RacingNumber":"1","PitStopTime":"2.6","PitLaneTime":"23.604","Lap":"12"}}]}}\r\n'
    b'01:13:41.855{"PitTimes":{"1":{"1":{"Timestamp":"2025-06-15T18:18:46.909Z","PitStop":'
    b'{"RacingNumber":"1","PitStopTime":"2.6","PitLaneTime":"23.604","Lap":"12"}}}}}\r\n'
    b'01:14:55.436{"PitTimes":{"63":[{"Timestamp":"2025-06-15T18:20:00.49Z","PitStop":'
    b'{"RacingNumber":"63","PitStopTime":"2.5","PitLaneTime":"23.231","Lap":"13"}}]}}\r\n'
    b'01:14:55.514{"PitTimes":{"63":{"1":{"Timestamp":"2025-06-15T18:20:00.568Z","PitStop":'
    b'{"RacingNumber":"63","PitStopTime":"2.5","PitLaneTime":"23.231","Lap":"13"}}}}}\r\n'
)


def test_a_stop_f1_sends_under_two_places_is_counted_once():
    """Each of these two stops arrives as the first of its driver's list and
    again, a tenth of a second later, as the second. The stops were matched
    to the timing by driver and lap, so one was published for each; the count
    beside them, in coverage.json, was of places: 62 for the race's 33."""
    stops = parse_pit_stop_series(CANADA)

    assert [(item["driver_number"], item["lap_number"], item["stationary_ms"]) for item in stops] == [
        ("1", 12, 2_600),
        ("63", 13, 2_500),
    ]
    assert measure_coverage(make_race(), "R", {**extras(), PIT_STOP_SERIES: CANADA})["pit_stops_in_series"] == 2


def test_the_count_in_a_generation_is_of_the_stops_beside_it():
    twice = pit_line("01:00:00.000", [stop("5", "2.4", "19.9", "2026-06-28T12:16:00.000Z")]) + pit_line(
        "01:00:00.100", {"1": stop("5", "2.4", "19.9", "2026-06-28T12:16:00.100Z")}
    )

    files = built(found={**extras(pit_stops=False), PIT_STOP_SERIES: twice})

    vouched = [row for row in read(files, "pit-stops.json") if row["stationary_ms"] is not None]
    assert len(vouched) == read(files, "coverage.json")["pit_stops_in_series"] == 1


def test_the_later_of_two_stops_with_one_lap_is_the_one_that_stands_and_one_with_no_lap_has_no_twin():
    feed = (
        pit_line("01:00:00.000", [stop("5", "9.9", "30.0", "2026-06-28T12:16:00.000Z")])
        + pit_line("01:00:01.000", {"1": stop("5", "2.4", "19.9", "2026-06-28T12:16:01.000Z")})
        + pit_line("01:00:02.000", {"2": stop("", "3.0", "20.0", "2026-06-28T12:30:00.000Z")})
        + pit_line("01:00:03.000", {"3": stop("", "3.1", "20.1", "2026-06-28T12:40:00.000Z")})
    )

    assert [(item["lap_number"], item["stationary_ms"]) for item in parse_pit_stop_series(feed)] == [
        (5, 2_400),
        (None, 3_000),
        (None, 3_100),
    ]


# --- R13-2: a fetch that loads the weather keeps the feed's own lines, or is no fetch ---


def answering(statuses: dict[str, int]):
    """FastF1's request function, answering each host with a status, and what was asked of it."""
    asked: list[str] = []

    def requests_get(url, headers=None):
        asked.append(url)
        host = url.split("/static/")[0]
        status = statuses.get(host, 200)
        if status is None:
            raise ConnectionError("no route to host")
        return SimpleNamespace(status_code=status, content=b"00:00:38.376{}" if status == 200 else b"<html>")

    fastf1 = SimpleNamespace(
        Cache=SimpleNamespace(requests_get=requests_get),
        mvapi=SimpleNamespace(get_circuit_info=lambda year, circuit_key: None),
    )
    return fastf1, asked


F1 = "https://livetiming.formula1.com"
MIRROR = "https://livetiming-mirror.fastf1.dev"


@pytest.mark.parametrize("refusal", [403, 500, None])
def test_the_weather_is_asked_of_the_mirror_when_f1_does_not_answer_and_the_pit_stops_are_not(refusal):
    """FastF1 loads a feed from its mirror when F1 refuses. The second
    request for the weather went to F1 alone, so a session loaded that way
    was archived without the lines and built with FastF1's zeros."""
    fastf1, asked = answering({F1: refusal})

    found = fetch_extras(fastf1, session(), ARCHIVE_PATH)

    assert found == {WEATHER_SERIES: b"00:00:38.376{}"}
    assert asked == [
        f"{F1}/static/{ARCHIVE_PATH}PitStopSeries.jsonStream",
        f"{F1}/static/{ARCHIVE_PATH}WeatherData.jsonStream",
        f"{MIRROR}/static/{ARCHIVE_PATH}WeatherData.jsonStream",
    ]


def test_the_mirror_is_not_asked_when_f1_answers():
    fastf1, asked = answering({})

    fetch_extras(fastf1, session(), ARCHIVE_PATH)

    assert not any(url.startswith(MIRROR) for url in asked)


class NoWeather:
    @property
    def weather_data(self):
        raise RuntimeError("The data you are trying to access has not been loaded yet. See `Session.load`")


def test_a_fetch_that_loaded_the_weather_and_could_not_keep_its_lines_is_not_one_to_archive():
    with_weather = make_race()
    without = make_race()
    without.weather_data = without.weather_data.iloc[0:0]

    assert weather_lines_are_kept(with_weather, {WEATHER_SERIES: b"00:00:38.376{}"})
    assert not weather_lines_are_kept(with_weather, {})
    assert not weather_lines_are_kept(with_weather, extras())
    # No weather loaded: there are no lines for anything to be the lines of.
    assert weather_lines_are_kept(without, {})
    assert weather_lines_are_kept(NoWeather(), {})
    assert weather_lines_are_kept(SimpleNamespace(weather_data=None), {})


def test_a_whole_fetch_refuses_to_archive_weather_without_its_lines(monkeypatch, tmp_path):
    """``fetch_session`` itself, with FastF1 and the network stood in for."""
    from contextlib import contextmanager

    from f1data import fetch as fetch_module

    loaded = make_race()
    loaded.load = lambda **kwargs: None
    fastf1 = SimpleNamespace(get_session=lambda year, event, code: loaded)

    @contextmanager
    def cache(cache_dir):
        yield fastf1

    monkeypatch.setattr(fetch_module, "fastf1_cache", cache)
    monkeypatch.setattr(fetch_module, "identity_from_fastf1", lambda found: SimpleNamespace(archive_path=ARCHIVE_PATH, session_type="R"))
    monkeypatch.setattr(fetch_module, "_versions", lambda module: {})
    monkeypatch.setattr(fetch_module, "fetch_extras", lambda module, found, path: extras())

    with pytest.raises(fetch_module.FetchError, match="WeatherData.jsonStream could not be fetched"):
        fetch_module.fetch_session(2026, 8, "R", tmp_path / "cache")

    monkeypatch.setattr(
        fetch_module, "fetch_extras", lambda module, found, path: {**extras(), WEATHER_SERIES: b"00:00:38.376{}"}
    )
    fetched = fetch_module.fetch_session(2026, 8, "R", tmp_path / "again")
    assert WEATHER_SERIES in fetched.extras


# --- R13-3: two cars a feed gives one code are still two cars ---------------------


def test_two_cars_with_one_code_are_two_drivers():
    """Car 2 carries car 1's code on its laps and in the driver list. Both
    cars' laps were published as one driver's, with one car's telemetry for
    each lap number and one car's coverage."""
    session_with_a_twin = make_race()
    session_with_a_twin.laps.loc[session_with_a_twin.laps["DriverNumber"] == "2", "Driver"] = "AAA"
    session_with_a_twin.results.loc["2", "Abbreviation"] = "AAA"

    codes = normalize.driver_codes(session_with_a_twin)
    files = built(session_with_a_twin, official=None)

    assert codes == {"1": "AAA", "2": "2", "3": "CCC"}
    assert [row["code"] for row in read(files, "drivers.json")] == ["AAA", "2", "CCC"]
    laps = read(files, "laps.json")
    assert len({(row["driver_code"], row["lap_number"]) for row in laps}) == len(laps)
    assert {"telemetry/AAA.json", "telemetry/2.json", "telemetry/CCC.json"} <= set(files)
    assert sorted(row["driver_code"] for row in read(files, "results.json")) == ["2", "AAA", "CCC"]
    assert [row["driver_code"] for row in read(files, "coverage.json")["drivers"]] == ["2", "AAA", "CCC"]
    # Whichever table says it.
    assert driver_codes(
        pd.DataFrame({"Abbreviation": ["AAA", "AAA"]}, index=["1", "2"]), pd.DataFrame()
    ) == {"1": "AAA", "2": "2"}


# --- R13-4: two lines of the weather feed with one time are two lines -------------

SAME_MOMENT = (
    b'00:10:00.000{"AirTemp":"21.0"}\r\n'
    b'00:10:00.000{"Rainfall":"1"}\r\n'
    b'00:11:00.000{"AirTemp":"21.4","Rainfall":"0"}\r\n'
)


def test_each_of_two_weather_lines_with_one_time_keeps_what_it_gave():
    """What the two give was intersected, which is nothing: both samples
    were published with no readings, the temperature and the rain included."""
    session_with_weather = make_race()
    session_with_weather.weather_data = weather_as_fastf1_parses(SAME_MOMENT)
    assert len(session_with_weather.weather_data) == 3

    assert weather_readings_sent(SAME_MOMENT)[600_000] == [frozenset({"AirTemp"}), frozenset({"Rainfall"})]
    samples = [
        artifact_json(sample)
        for sample in normalize.weather(session_with_weather, "P1", {WEATHER_SERIES: SAME_MOMENT})
    ]

    assert [(row["time_ms"], row["air_temp_c"], row["rainfall"]) for row in samples] == [
        (600_000, 21.0, None),
        (600_000, None, True),
        (660_000, 21.4, False),
    ]
    # A sample more than the feed has lines for at its time has no readings.
    fewer = SAME_MOMENT.split(b"\r\n", 1)[1]
    _, second, _ = normalize.weather(session_with_weather, "P1", {WEATHER_SERIES: fewer})
    assert (second.air_temp_c, second.track_temp_c, second.rainfall, second.wind_speed_kph) == (None,) * 4


# --- R13-5: what F1 takes back of a driver's stops is gone ------------------------


def test_a_stop_f1_deletes_is_not_published():
    feed = (
        pit_line("01:00:00.000", [stop("5", "2.4", "19.9", "2026-06-28T12:16:00.000Z")])
        + pit_line("01:00:10.000", {"1": stop("9", "3.0", "20.5", "2026-06-28T12:25:00.000Z")})
        + pit_line("01:00:20.000", {"_deleted": [1]})
    )

    assert [item["lap_number"] for item in parse_pit_stop_series(feed)] == [5]
    # Deleting what is not there, or with something that is no place, deletes nothing.
    for nothing in ({"_deleted": [7]}, {"_deleted": "all"}, {"_deleted": [True, "1", None]}):
        kept = parse_pit_stop_series(feed.rsplit(b"\r\n", 2)[0] + b"\r\n" + pit_line("01:00:20.000", nothing))
        assert [item["lap_number"] for item in kept] == [5, 9]


def test_a_drivers_list_sent_again_is_the_whole_of_that_drivers_stops():
    feed = (
        pit_line("01:00:00.000", [stop("5", "2.4", "19.9", "2026-06-28T12:16:00.000Z")])
        + pit_line("01:00:10.000", {"1": stop("9", "3.0", "20.5", "2026-06-28T12:25:00.000Z")})
        + pit_line("01:00:20.000", [stop("5", "2.5", "19.9")])
    )
    # Another driver's list says nothing of this one's.
    another = (
        b'01:00:30.000{"PitTimes":{"2":[{"PitStop":{"RacingNumber":"2","PitStopTime":"3.1",'
        b'"PitLaneTime":"21.0","Lap":"8"}}]}}'
    )

    stops = parse_pit_stop_series(feed + another)

    assert [(item["driver_number"], item["lap_number"], item["stationary_ms"]) for item in stops] == [
        ("1", 5, 2_500),
        ("2", 8, 3_100),
    ]


# --- the zero F1 sends for a sensor with no reading (found by the frontend) --------

# Three lines of the 2026 Azerbaijan GP's weather feed, a minute apart, as F1 sent them.
AZERBAIJAN = (
    b'00:04:02.057{"AirTemp":"26.2","Humidity":"58.9","Pressure":"1023.2","Rainfall":"0","TrackTemp":"46.6",'
    b'"WindDirection":"182","WindSpeed":"0.9"}\r\n'
    b'00:05:02.054{"AirTemp":"26.2","Humidity":"58.6","Pressure":"1023.2","Rainfall":"0","TrackTemp":"0.0",'
    b'"WindDirection":"233","WindSpeed":"1.2"}\r\n'
    b'00:06:02.058{"AirTemp":"26.2","Humidity":"58.4","Pressure":"1023.2","Rainfall":"0","TrackTemp":"47.3",'
    b'"WindDirection":"201","WindSpeed":"0.0"}\r\n'
)


@pytest.mark.parametrize("kept", [True, False], ids=["with the feed's lines", "a snapshot from before they were kept"])
def test_a_track_at_zero_between_two_readings_of_forty_six_degrees_is_a_sensor_with_no_reading(kept):
    """The site drew two spikes to 0 degrees in this race and called its
    track "0.0-48.1C". The line gives the reading, as "0.0": it is F1's own
    stand-in for none, and neither FastF1 nor the feed's lines can say so."""
    session_with_weather = make_race()
    session_with_weather.weather_data = weather_as_fastf1_parses(AZERBAIJAN)
    found = {**extras(), WEATHER_SERIES: AZERBAIJAN} if kept else extras()

    files = built(session_with_weather, found=found)

    samples = read(files, "weather.json")
    assert [row["track_temp_c"] for row in samples] == [46.6, None, 47.3]
    assert [row["air_temp_c"] for row in samples] == [26.2, 26.2, 26.2]
    # Still air is a reading.
    assert [row["wind_speed_kph"] for row in samples] == [3.2, 4.3, 0.0]
    assert read(files, "summary.json")["weather_summary"] == "air 26.2-26.2C, track 46.6-47.3C, dry"


def temperatures(*values: float | None) -> list[float | None]:
    lines = b"".join(
        (
            f'00:{minute:02d}:00.000{{"AirTemp":"{value}","Humidity":"50.0","Pressure":"1000.0","Rainfall":"0",'
            f'"TrackTemp":"30.0","WindDirection":"0","WindSpeed":"1.0"}}\r\n'
        ).encode()
        for minute, value in enumerate(values)
    )
    session_with_weather = make_race()
    session_with_weather.weather_data = weather_as_fastf1_parses(lines)
    return [sample.air_temp_c for sample in normalize.weather(session_with_weather, "P1", extras())]


def test_a_zero_is_a_reading_unless_both_its_neighbours_say_it_cannot_be():
    # A cold morning: zero between one degree and half a degree below.
    assert temperatures(1.0, 0.0, -0.5) == [1.0, 0.0, -0.5]
    # Near on one side is enough to believe it.
    assert temperatures(25.0, 0.0, 3.0) == [25.0, 0.0, 3.0]
    # First and last of the feed, with the one neighbour each has.
    assert temperatures(0.0, 26.0, 26.1, 0.0) == [None, 26.0, 26.1, None]
    # Two in a row, between readings.
    assert temperatures(26.0, 0.0, 0.0, 26.2) == [26.0, None, None, 26.2]
    # Nothing but zeros has nothing to be judged against.
    assert temperatures(0.0, 0.0) == [0.0, 0.0]
    # Far below zero is as far as far above.
    assert temperatures(-25.0, 0.0, -24.0) == [-25.0, None, -24.0]
