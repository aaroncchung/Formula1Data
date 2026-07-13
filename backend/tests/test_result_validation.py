from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.result_validation import InvalidSessionResultsError, validate_final_results


class ResultValidationTests(unittest.TestCase):
    def test_rejects_placeholder_classification(self):
        rows = [
            {
                "driver_code": "ANT",
                "position": 0,
                "classified_position": "nan",
                "status": None,
                "points": None,
                "grid": None,
                "laps": None,
            },
            {
                "driver_code": "NOR",
                "position": 0,
                "classified_position": "nan",
                "status": None,
                "points": None,
                "grid": None,
                "laps": None,
            },
        ]

        with self.assertRaisesRegex(InvalidSessionResultsError, "unique positions"):
            validate_final_results("2026-04-r", rows)

    def test_accepts_complete_classification_with_retirements(self):
        rows = [
            {
                "driver_code": "ANT",
                "position": 1,
                "classified_position": "1",
                "status": "Finished",
                "points": 25.0,
                "grid": 1,
                "laps": 57,
            },
            {
                "driver_code": "GAS",
                "position": 2,
                "classified_position": "R",
                "status": "Retired",
                "points": 0.0,
                "grid": 2,
                "laps": 4,
            },
        ]

        validate_final_results("2026-04-r", rows)


if __name__ == "__main__":
    unittest.main()
