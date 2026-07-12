from __future__ import annotations

import unittest
from datetime import date

from pipeline.schedule_ingestion import select_candidates


class ScheduleIngestionTests(unittest.TestCase):
    def test_selects_completed_recent_sessions(self):
        catalog = {
            "meetings": [
                {
                    "meeting_id": "2026-09-british-grand-prix",
                    "year": 2026,
                    "round": 9,
                    "name": "British Grand Prix",
                    "start_date": "2026-07-05T00:00:00",
                    "sessions_available": ["FP1", "Q", "R"],
                },
                {
                    "meeting_id": "2026-10-belgian-grand-prix",
                    "year": 2026,
                    "round": 10,
                    "name": "Belgian Grand Prix",
                    "start_date": "2026-07-19T00:00:00",
                    "sessions_available": ["R"],
                },
            ]
        }

        candidates = select_candidates(
            catalog,
            through_date=date(2026, 7, 6),
            lookback_days=4,
            years=set(),
            sessions=set(),
            races_only=True,
        )

        self.assertEqual(
            candidates,
            [
                {
                    "year": 2026,
                    "round": 9,
                    "session": "R",
                    "meeting_id": "2026-09-british-grand-prix",
                    "meeting_name": "British Grand Prix",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
