"""The feeds a build needs that FastF1 does not load with a session (rule 4)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES, fetch_extras

ARCHIVE_PATH = "2026/2026-06-07_Monaco_Grand_Prix/2026-06-07_Race/"


def markers(with_distance: bool) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {"X": -7600.0, "Y": -6700.0, "Number": 1, "Letter": "", "Angle": 142.0},
            {"X": -5100.0, "Y": -9200.0, "Number": 10, "Letter": "A", "Angle": 12.5},
        ]
    )
    if with_distance:
        frame["Distance"] = [118.4, 1650.25]
    return frame


class CircuitInfo:
    """As ``fastf1.mvapi.get_circuit_info`` returns it: markers, no distances yet."""

    def __init__(self, placing_fails: bool = False):
        self.rotation = 44.0
        self.corners = markers(with_distance=False)
        self.marshal_lights = pd.DataFrame()
        self.marshal_sectors = pd.DataFrame()
        self._placing_fails = placing_fails

    def add_marker_distance(self, reference_lap):
        if self._placing_fails:
            raise ValueError("no position data for the reference lap")
        self.corners = markers(with_distance=True)


def fastf1_answering(pit_stop_status: int = 200, circuit: object = None):
    requested: list[str] = []
    asked_for: list[dict] = []

    def requests_get(url, headers=None):
        requested.append(url)
        content = b"01:12:03.942{}" if pit_stop_status == 200 else b"<html>AccessDenied</html>"
        return SimpleNamespace(status_code=pit_stop_status, content=content)

    def get_circuit_info(year, circuit_key):
        asked_for.append({"year": year, "circuit_key": circuit_key})
        return circuit

    return SimpleNamespace(
        Cache=SimpleNamespace(requests_get=requests_get),
        mvapi=SimpleNamespace(get_circuit_info=get_circuit_info),
        requested=requested,
        asked_for=asked_for,
    )


def session(circuit_key: int = 22, short_name: str = "Monte Carlo"):
    return SimpleNamespace(
        session_info={"Meeting": {"Circuit": {"Key": circuit_key, "ShortName": short_name}}},
        event=SimpleNamespace(year=2026),
        laps=SimpleNamespace(pick_fastest=lambda: "the fastest lap"),
    )


def test_both_are_fetched_by_name():
    fastf1 = fastf1_answering(circuit=CircuitInfo())

    extras = fetch_extras(fastf1, session(), ARCHIVE_PATH)

    assert fastf1.requested == [
        f"https://livetiming.formula1.com/static/{ARCHIVE_PATH}PitStopSeries.jsonStream",
        f"https://livetiming.formula1.com/static/{ARCHIVE_PATH}WeatherData.jsonStream",
    ]
    assert fastf1.asked_for == [{"year": 2026, "circuit_key": 22}]
    assert extras[PIT_STOP_SERIES] == b"01:12:03.942{}"
    circuit = json.loads(extras[CIRCUIT_INFO])
    assert circuit["rotation"] == 44.0
    assert circuit["corners"] == [
        {"number": 1, "letter": "", "x": -7600.0, "y": -6700.0, "angle": 142.0, "distance_m": 118.4},
        {"number": 10, "letter": "A", "x": -5100.0, "y": -9200.0, "angle": 12.5, "distance_m": 1650.25},
    ]


def test_corners_are_kept_when_they_cannot_be_placed_along_the_lap():
    """The 2026 Monaco race: the position feed stops in lap 5, placing the
    markers fails, and the corners themselves were lost with it."""
    extras = fetch_extras(fastf1_answering(circuit=CircuitInfo(placing_fails=True)), session(), ARCHIVE_PATH)

    corners = json.loads(extras[CIRCUIT_INFO])["corners"]
    assert [corner["number"] for corner in corners] == [1, 10]
    assert [corner["distance_m"] for corner in corners] == [None, None]


def test_a_feed_f1_does_not_hold_is_left_out_not_stored_as_an_error_page():
    extras = fetch_extras(fastf1_answering(pit_stop_status=403, circuit=CircuitInfo()), session(), ARCHIVE_PATH)

    assert PIT_STOP_SERIES not in extras
    assert CIRCUIT_INFO in extras


def test_a_circuit_multiviewer_does_not_have_is_left_out():
    extras = fetch_extras(fastf1_answering(circuit=None), session(), ARCHIVE_PATH)

    assert CIRCUIT_INFO not in extras
    assert PIT_STOP_SERIES in extras


def test_nothing_raises_out_of_a_fetch():
    def broken(*args, **kwargs):
        raise ConnectionError("network down")

    fastf1 = SimpleNamespace(
        Cache=SimpleNamespace(requests_get=broken), mvapi=SimpleNamespace(get_circuit_info=broken)
    )

    assert fetch_extras(fastf1, session(), ARCHIVE_PATH) == {}
