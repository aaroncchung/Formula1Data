from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.normalizer import (
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


if __name__ == "__main__":
    unittest.main()
