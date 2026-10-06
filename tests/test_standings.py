"""Standings come whole from Jolpica and change in place (AR-15; section 6, rule 2)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pandas as pd
import pytest

from f1data import layout
from f1data.standings import fetch_standings, publish_standings
from f1data.store import MemoryStore
from tests.test_publish import Interposing


def standings(round_number: int = 9, ant_points: float = 179, rounds: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "format_version": 1,
        "year": 2026,
        "rounds": rounds or {"drivers": round_number, "constructors": round_number},
        "drivers": [
            {"position": 1, "points": ant_points, "driver_code": "ANT"},
            {"position": 2, "points": 154, "driver_code": "RUS"},
        ],
        "constructors": [{"position": 1, "points": ant_points + 154, "name": "Mercedes"}],
    }


def stored(store) -> dict:
    return json.loads(store.get(layout.standings_key(2026)).data)


def test_standings_are_published_then_left_alone_until_they_change():
    store = MemoryStore()

    assert publish_standings(store, 2026, lambda year: standings()) == "published"
    assert publish_standings(store, 2026, lambda year: standings()) == "current"
    assert stored(store)["drivers"][0] == {"position": 1, "points": 179, "driver_code": "ANT"}


def test_a_new_round_replaces_the_stored_standings():
    store = MemoryStore()
    publish_standings(store, 2026, lambda year: standings(9))

    assert publish_standings(store, 2026, lambda year: standings(10, ant_points=204)) == "published"
    assert stored(store)["rounds"] == {"drivers": 10, "constructors": 10}


def test_a_correction_within_a_round_is_published():
    """Criterion 2: a standings update that does not advance the round."""
    store = MemoryStore()
    publish_standings(store, 2026, lambda year: standings(9, ant_points=179))

    assert publish_standings(store, 2026, lambda year: standings(9, ant_points=171)) == "published"
    assert stored(store)["drivers"][0]["points"] == 171


def test_a_slow_run_cannot_move_the_standings_back_a_round():
    store = MemoryStore()
    publish_standings(store, 2026, lambda year: standings(10, ant_points=204))

    assert publish_standings(store, 2026, lambda year: standings(9)) == "behind"
    assert stored(store)["rounds"]["drivers"] == 10


def test_one_table_behind_is_behind():
    store = MemoryStore()
    publish_standings(store, 2026, lambda year: standings(10))
    lagging = standings(rounds={"drivers": 10, "constructors": 9})

    assert publish_standings(store, 2026, lambda year: lagging) == "behind"


def test_no_standings_before_the_first_round_writes_nothing():
    store = MemoryStore()

    assert publish_standings(store, 2027, lambda year: None) == "unavailable"
    assert store.get(layout.standings_key(2027)) is None


def test_the_loser_of_the_write_fetches_again_and_decides_again():
    """A run that fetched round 9 loses to one that published round 10. It
    must not then put its round 9 over it."""
    store = Interposing(MemoryStore())
    publish_standings(store, 2026, lambda year: standings(8, ant_points=150))
    answers = iter([standings(9), standings(10, ant_points=204)])
    fetches = []

    def slow_fetch(year):
        fetches.append(year)
        return next(answers)

    store.before_put[layout.standings_key(2026)] = lambda: publish_standings(
        store, 2026, lambda year: standings(10, ant_points=204)
    )

    outcome = publish_standings(store, 2026, slow_fetch)

    assert outcome == "current"
    assert len(fetches) == 2
    assert stored(store)["rounds"]["drivers"] == 10


def test_two_first_publications_do_not_both_win():
    store = Interposing(MemoryStore())
    store.before_put[layout.standings_key(2026)] = lambda: publish_standings(
        store, 2026, lambda year: standings(10, ant_points=204)
    )

    assert publish_standings(store, 2026, lambda year: standings(9)) == "behind"
    assert stored(store)["rounds"]["drivers"] == 10


# --- reading Jolpica ----------------------------------------------------------


class Jolpica:
    def __init__(self, drivers, constructors, failures=0):
        outer = self
        self.failures = failures
        self.cache_disabled: list[bool] = []
        self._disabled = False

        class Client:
            def __init__(self, **kwargs):
                pass

            def get_driver_standings(self, season, limit=None):
                return outer._answer(drivers)

            def get_constructor_standings(self, season, limit=None):
                return outer._answer(constructors)

        @contextmanager
        def disabled():
            outer._disabled = True
            try:
                yield
            finally:
                outer._disabled = False

        self.ergast = SimpleNamespace(Ergast=Client)
        self.Cache = SimpleNamespace(disabled=disabled)

    def _answer(self, table):
        self.cache_disabled.append(self._disabled)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("429 Too Many Requests")
        frame, round_number = table
        return SimpleNamespace(content=[frame], description=pd.DataFrame([{"season": 2026, "round": round_number}]))


DRIVERS = pd.DataFrame(
    [
        {"position": 1, "points": 320.0, "wins": 8, "driverCode": "ANT", "driverNumber": 12,
         "givenName": "Andrea Kimi", "familyName": "Antonelli", "constructorNames": ["Mercedes"]},
        {"position": 2, "points": 236.5, "wins": 3, "driverCode": "RUS", "driverNumber": 63,
         "givenName": "George", "familyName": "Russell", "constructorNames": ["Mercedes"]},
    ]
)
CONSTRUCTORS = pd.DataFrame(
    [{"position": 1, "points": 556.5, "wins": 11, "constructorId": "mercedes", "constructorName": "Mercedes"}]
)


def test_both_tables_are_asked_for_uncached_and_reduced_to_plain_values():
    jolpica = Jolpica((DRIVERS, 16), (CONSTRUCTORS, 16))

    fetched = fetch_standings(jolpica, 2026)

    assert jolpica.cache_disabled == [True, True]
    assert fetched["rounds"] == {"drivers": 16, "constructors": 16}
    assert fetched["drivers"][0] == {
        "position": 1,
        "points": 320,
        "wins": 8,
        "driver_code": "ANT",
        "driver_number": 12,
        "given_name": "Andrea Kimi",
        "family_name": "Antonelli",
        "constructors": ["Mercedes"],
    }
    assert fetched["drivers"][1]["points"] == 236.5
    assert fetched["constructors"] == [
        {"position": 1, "points": 556.5, "wins": 11, "constructor_id": "mercedes", "name": "Mercedes"}
    ]
    # Plain JSON all the way down.
    json.dumps(fetched)


def test_a_season_that_has_not_started_has_no_standings():
    jolpica = Jolpica((pd.DataFrame(), 0), (pd.DataFrame(), 0))

    assert fetch_standings(jolpica, 2027) is None


def test_a_refused_request_is_asked_again():
    pauses: list[float] = []
    jolpica = Jolpica((DRIVERS, 16), (CONSTRUCTORS, 16), failures=1)

    assert fetch_standings(jolpica, 2026, sleep=pauses.append)["rounds"]["drivers"] == 16
    assert pauses == [2.0]


def test_a_request_that_keeps_failing_raises():
    jolpica = Jolpica((DRIVERS, 16), (CONSTRUCTORS, 16), failures=3)

    with pytest.raises(RuntimeError):
        fetch_standings(jolpica, 2026, sleep=lambda seconds: None)
