from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.normalizer import (
    IncompleteFastF1SessionError,
    normalize_fastf1_session,
    pd,
    selected_session_codes,
    session_code_for_name,
    session_start_time_from_event,
    sessions_available_from_event,
)


class SessionMetadataTests(unittest.TestCase):
    def test_schedule_session_codes_are_derived_from_fastf1_metadata(self):
        row = {
            "Session1": "Practice 1",
            "Session2": "Sprint Qualifying",
            "Session3": "Sprint",
            "Session4": "Qualifying",
            "Session5": "Race",
            "Session2DateUtc": "2026-04-10T15:00:00+00:00",
        }

        self.assertEqual(session_code_for_name("sprint shootout"), "SQ")
        self.assertEqual(sessions_available_from_event(row), ["FP1", "SQ", "S", "Q", "R"])
        self.assertEqual(session_start_time_from_event(row, "SQ"), "2026-04-10T15:00:00+00:00")

    def test_session_selection_defaults_to_all_available_sessions(self):
        row = {
            "RoundNumber": 4,
            "EventName": "Test Grand Prix",
            "Country": "Testland",
            "Location": "Test City",
            "CircuitName": "Test Circuit",
            "Session1": "Practice 1",
            "Session2": "Sprint Qualifying",
            "Session3": "Sprint",
            "Session4": "Qualifying",
            "Session5": "Race",
        }

        self.assertEqual(selected_session_codes(row), ["FP1", "SQ", "S", "Q", "R"])
        self.assertEqual(selected_session_codes(row, sessions=["Q", "Race"]), ["Q", "R"])

    def test_session_selection_can_preserve_race_only_behavior(self):
        row = {
            "RoundNumber": 4,
            "EventName": "Test Grand Prix",
            "Session1": "Practice 1",
            "Session2": "Qualifying",
            "Session3": "Race",
        }
        self.assertEqual(selected_session_codes(row, races_only=True), ["R"])

    @unittest.skipIf(pd is None, "pandas is required for FastF1 normalization tests")
    def test_unloaded_required_lap_data_fails_clearly(self):
        session = FakeFastF1Session(laps_error=RuntimeError("The data has not been loaded yet."))

        with self.assertRaisesRegex(IncompleteFastF1SessionError, "FastF1 did not load laps"):
            normalize_fastf1_session(2024, 8, "R", session)

    @unittest.skipIf(pd is None, "pandas is required for FastF1 normalization tests")
    def test_unloaded_optional_session_frames_degrade_to_empty_sections(self):
        laps = pd.DataFrame(
            [
                {
                    "Driver": "VER",
                    "LapNumber": 1,
                    "LapTime": None,
                    "Sector1Time": None,
                    "Sector2Time": None,
                    "Sector3Time": None,
                    "Compound": "MEDIUM",
                    "TyreLife": 1,
                    "Stint": 1,
                    "Position": 1,
                    "PitInTime": None,
                    "PitOutTime": None,
                    "Deleted": False,
                    "IsAccurate": True,
                    "TrackStatus": "1",
                }
            ]
        )
        session = FakeFastF1Session(
            laps=laps,
            results_error=RuntimeError("results unavailable"),
            weather_error=RuntimeError("weather unavailable"),
            race_control_error=RuntimeError("messages unavailable"),
        )
        session.name = "Practice 1"
        session.event = {**session.event, "Session1": "Practice 1"}

        dataset = normalize_fastf1_session(2024, 8, "FP1", session)
        session_data = dataset["session_data"]["2024-08-fp1"]

        self.assertEqual(len(session_data["laps"]), 1)
        self.assertEqual(session_data["drivers"], [])
        self.assertEqual(session_data["results"], [])
        self.assertEqual(session_data["weather"], [])
        self.assertEqual(session_data["race_control"], [])

    @unittest.skipIf(pd is None, "pandas is required for FastF1 normalization tests")
    def test_race_with_placeholder_results_is_rejected(self):
        laps = pd.DataFrame([{"Driver": "ANT", "LapNumber": 1}])
        results = pd.DataFrame(
            [
                {
                    "Abbreviation": "ANT",
                    "Position": float("nan"),
                    "ClassifiedPosition": float("nan"),
                    "Status": None,
                    "Points": float("nan"),
                    "GridPosition": float("nan"),
                    "Time": pd.NaT,
                    "Laps": float("nan"),
                },
                {
                    "Abbreviation": "NOR",
                    "Position": float("nan"),
                    "ClassifiedPosition": float("nan"),
                    "Status": None,
                    "Points": float("nan"),
                    "GridPosition": float("nan"),
                    "Time": pd.NaT,
                    "Laps": float("nan"),
                },
            ]
        )
        session = FakeFastF1Session(laps=laps, results=results)

        with self.assertRaisesRegex(
            IncompleteFastF1SessionError, "must contain unique positions"
        ):
            normalize_fastf1_session(2026, 4, "R", session)


class FakeFastF1Session:
    event = {
        "RoundNumber": 8,
        "EventName": "Monaco Grand Prix",
        "Country": "Monaco",
        "Location": "Monte Carlo",
        "CircuitName": "Circuit de Monaco",
        "Session5": "Race",
    }
    name = "Race"

    def __init__(
        self,
        laps=None,
        laps_error=None,
        results_error=None,
        results=None,
        weather_error=None,
        race_control_error=None,
    ):
        self._laps = laps
        self._laps_error = laps_error
        self._results_error = results_error
        self._results = results
        self._weather_error = weather_error
        self._race_control_error = race_control_error

    @property
    def laps(self):
        if self._laps_error:
            raise self._laps_error
        return self._laps if self._laps is not None else pd.DataFrame()

    @property
    def results(self):
        if self._results_error:
            raise self._results_error
        return self._results if self._results is not None else pd.DataFrame()

    @property
    def weather_data(self):
        if self._weather_error:
            raise self._weather_error
        return pd.DataFrame()

    @property
    def race_control_messages(self):
        if self._race_control_error:
            raise self._race_control_error
        return pd.DataFrame()


if __name__ == "__main__":
    unittest.main()
