from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.backfill import backfill_candidate, parse_iso_date


class BackfillTests(unittest.TestCase):
    def test_parse_iso_date_accepts_datetime_prefix(self):
        self.assertEqual(parse_iso_date("2026-07-05T20:00:00+00:00"), date(2026, 7, 5))

    def test_candidate_marks_future_sessions(self):
        event = {
            "RoundNumber": 9,
            "Session5": "Race",
            "Session5DateUtc": "2026-07-06T20:00:00+00:00",
        }

        candidate = backfill_candidate(
            year=2026,
            event=event,
            session_code="R",
            through_date=date(2026, 7, 5),
        )

        self.assertEqual(candidate.session_id, "2026-09-r")
        self.assertEqual(candidate.start_date, date(2026, 7, 6))
        self.assertTrue(candidate.is_future)


if __name__ == "__main__":
    unittest.main()
