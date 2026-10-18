"""The official result, from Jolpica (AR-15)."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pandas as pd
import pytest

from f1data.classification import (
    ClassificationUnavailable,
    fetch_classification,
    fingerprint,
    merge_into_session,
)


def result_frame(**overrides):
    rows = [
        {"number": 63, "driverCode": "RUS", "position": 1, "positionText": "1", "grid": 1, "status": "Finished",
         "points": 25.0, "laps": 71, "totalRaceTime": pd.Timedelta(hours=1, minutes=26, seconds=37.979)},
        {"number": 3, "driverCode": "VER", "position": 2, "positionText": "2", "grid": 5, "status": "Finished",
         "points": 18.0, "laps": 71, "totalRaceTime": pd.Timedelta(seconds=1.611)},
        {"number": 77, "driverCode": "BOT", "position": 22, "positionText": "R", "grid": 20, "status": "Retired",
         "points": 0.0, "laps": 2, "totalRaceTime": pd.NaT},
    ]
    for index, changes in overrides.items():
        rows[int(index)].update(changes)
    return pd.DataFrame(rows)


class Jolpica:
    """Stands in for ``fastf1``: its Ergast client and its cache switch."""

    def __init__(self, answers, first_laps=()):
        self._answers = list(answers)
        # What each request for first-lap times is answered with. Past the
        # end of the list Jolpica has no lap times.
        self._first_laps = list(first_laps)
        self.lap_calls: list[tuple[int, int, int, bool]] = []
        self.calls: list[tuple[str, int, int]] = []
        self.cache_disabled_during_calls: list[bool] = []
        self._disabled = False
        outer = self

        class Client:
            def __init__(self, **kwargs):
                pass

            def get_race_results(self, season, round, limit=None):
                return outer._answer("race", season, round)

            def get_sprint_results(self, season, round, limit=None):
                return outer._answer("sprint", season, round)

            def get_lap_times(self, season, round, lap_number, limit=None):
                return outer._first_lap_answer(season, round, lap_number)

        @contextmanager
        def disabled():
            outer._disabled = True
            try:
                yield
            finally:
                outer._disabled = False

        self.ergast = SimpleNamespace(Ergast=Client)
        self.Cache = SimpleNamespace(disabled=disabled)

    def _answer(self, kind, season, round_number):
        self.calls.append((kind, season, round_number))
        self.cache_disabled_during_calls.append(self._disabled)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(content=[answer], description=getattr(self, "description", None))

    def _first_lap_answer(self, season, round_number, lap_number):
        self.lap_calls.append((season, round_number, lap_number, self._disabled))
        answer = self._first_laps.pop(0) if self._first_laps else None
        if isinstance(answer, Exception):
            raise answer
        # Jolpica says which race an answer is about. The same one as the
        # result's, unless a test sets ``lap_description`` to another.
        description = getattr(self, "lap_description", getattr(self, "description", None))
        return SimpleNamespace(content=[] if answer is None else [answer], description=description)


def test_the_result_is_asked_for_uncached_and_reduced_to_plain_rows():
    jolpica = Jolpica([result_frame()])

    classification = fetch_classification(jolpica, 2026, 8, "R")

    assert jolpica.calls == [("race", 2026, 8)]
    assert jolpica.cache_disabled_during_calls == [True]
    assert classification.rows[0] == {
        "number": 63,
        "driverCode": "RUS",
        "position": 1,
        "positionText": "1",
        "grid": 1,
        "status": "Finished",
        "points": 25,
        "laps": 71,
        "totalRaceTime": 5197979,
    }
    assert classification.rows[2]["totalRaceTime"] is None
    assert classification.laps_by_number == {"63": 71, "3": 71, "77": 2}
    assert classification.fingerprint == fingerprint(classification.rows)


def test_a_sprint_asks_for_the_sprint_result():
    jolpica = Jolpica([result_frame()])

    fetch_classification(jolpica, 2026, 2, "S")

    assert jolpica.calls == [("sprint", 2026, 2)]


def test_a_penalty_changes_the_fingerprint():
    """AR-15: the committed Monaco result has a driver third whom Jolpica has seventh."""
    before = fetch_classification(Jolpica([result_frame()]), 2026, 8, "R")
    after = fetch_classification(
        Jolpica([result_frame(**{"1": {"position": 7, "positionText": "7", "points": 6.0}})]), 2026, 8, "R"
    )
    same = fetch_classification(Jolpica([result_frame()]), 2026, 8, "R")

    assert before.fingerprint != after.fingerprint
    assert before.fingerprint == same.fingerprint


def test_a_refused_request_is_asked_again_before_giving_up():
    """Jolpica answered 429 to a fetch that followed twenty planning requests."""
    pauses: list[float] = []
    jolpica = Jolpica([RuntimeError("429 Too Many Requests"), result_frame()])

    classification = fetch_classification(jolpica, 2026, 8, "R", sleep=pauses.append)

    assert len(classification.rows) == 3
    assert pauses == [2.0]


def test_a_request_that_keeps_failing_is_unavailable_not_a_crash():
    pauses: list[float] = []
    jolpica = Jolpica([RuntimeError("429")] * 3)

    with pytest.raises(ClassificationUnavailable, match="after 3 attempts"):
        fetch_classification(jolpica, 2026, 8, "R", sleep=pauses.append)
    assert pauses == [2.0, 6.0]


def test_no_result_yet_is_unavailable_and_is_not_asked_for_twice():
    jolpica = Jolpica([pd.DataFrame()])

    with pytest.raises(ClassificationUnavailable, match="has no classification"):
        fetch_classification(jolpica, 2026, 16, "R", sleep=lambda seconds: None)
    assert len(jolpica.calls) == 1


def test_only_races_and_sprints_have_a_classification():
    with pytest.raises(ValueError):
        fetch_classification(Jolpica([]), 2026, 8, "Q")


def test_the_official_result_replaces_what_the_session_was_loaded_with():
    session = SimpleNamespace(
        results=pd.DataFrame(
            {
                "DriverNumber": ["63", "3", "77"],
                "Abbreviation": ["RUS", "VER", "BOT"],
                "TeamColor": ["27F4D2", "3671C6", "909090"],
                "Position": [2.0, 1.0, 22.0],
                "Points": [18.0, 25.0, 0.0],
                "Laps": [float("nan")] * 3,
            },
            index=["63", "3", "77"],
        )
    )

    merge_into_session(session, fetch_classification(Jolpica([result_frame()]), 2026, 8, "R"))

    merged = session._results
    assert list(merged["Abbreviation"]) == ["RUS", "VER", "BOT"]
    assert list(merged["Position"]) == [1, 2, 22]
    assert list(merged["Laps"]) == [71, 71, 2]
    assert list(merged["ClassifiedPosition"]) == ["1", "2", "R"]
    # What only F1's driver list knows is kept.
    assert list(merged["TeamColor"]) == ["27F4D2", "3671C6", "909090"]


def test_a_correction_to_a_name_changes_the_fingerprint_too():
    """Found in review: the build takes the constructor's and the driver's
    names from the result, and the fingerprint did not cover them."""
    before = fetch_classification(Jolpica([named_result()]), 2026, 8, "R")
    renamed_team = fetch_classification(Jolpica([named_result(constructorName="Mercedes-AMG")]), 2026, 8, "R")
    renamed_driver = fetch_classification(Jolpica([named_result(familyName="Russel")]), 2026, 8, "R")

    assert len({before.fingerprint, renamed_team.fingerprint, renamed_driver.fingerprint}) == 3


def named_result(**changes):
    frame = result_frame()
    frame["givenName"] = ["George", "Max", "Valtteri"]
    frame["familyName"] = ["Russell", "Verstappen", "Bottas"]
    frame["constructorName"] = ["Mercedes", "Red Bull", "Cadillac"]
    for column, value in changes.items():
        frame.loc[0, column] = value
    return frame


def test_the_result_says_which_race_it_is_the_result_of():
    jolpica = Jolpica([result_frame()])
    jolpica.description = pd.DataFrame([{"season": 2026, "round": 8, "raceDate": pd.Timestamp("2026-06-28")}])

    classification = fetch_classification(jolpica, 2026, 8, "R")

    assert classification.race_date.isoformat() == "2026-06-28"
    assert fetch_classification(Jolpica([result_frame()]), 2026, 8, "R").race_date is None
