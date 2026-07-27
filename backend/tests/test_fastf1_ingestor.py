from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.fastf1_ingestor import FastF1Ingestor


class GuessSessionIdTests(unittest.TestCase):
    def test_round_based_events_keep_their_zero_padded_id(self):
        ingestor = _ingestor({})

        self.assertEqual(ingestor._guess_session_id(2026, 9, "R"), "2026-09-r")
        self.assertEqual(ingestor._guess_session_id(2026, "9", "Race"), "2026-09-r")

    def test_name_based_events_resolve_the_round_from_the_stored_schedule(self):
        """A name slug never matched a session id, so the pre-check was dead."""
        ingestor = _ingestor(
            {
                "processed/seasons/2026/dataset.json": {
                    "meetings": [
                        {"year": 2026, "round": 8, "name": "Monaco Grand Prix"},
                        {"year": 2026, "round": 9, "name": "British Grand Prix"},
                    ]
                }
            }
        )

        self.assertEqual(
            ingestor._guess_session_id(2026, "Monaco Grand Prix", "Race"), "2026-08-r"
        )
        self.assertEqual(
            ingestor._guess_session_id(2026, "british grand prix", "Q"), "2026-09-q"
        )

    def test_an_unresolvable_event_name_yields_no_guess(self):
        ingestor = _ingestor(
            {"processed/seasons/2026/dataset.json": {"meetings": [{"year": 2026, "round": 8, "name": "Monaco Grand Prix"}]}}
        )

        self.assertIsNone(ingestor._guess_session_id(2026, "Belgian Grand Prix", "R"))
        self.assertIsNone(ingestor._guess_session_id(2025, "Monaco Grand Prix", "R"))

    def test_a_matching_dataset_short_circuits_the_fastf1_load(self):
        ingestor = _ingestor(
            {
                "processed/seasons/2026/dataset.json": {
                    "meetings": [{"year": 2026, "round": 8, "name": "Monaco Grand Prix"}]
                },
                "processed/sessions/2026-08-r/dataset.json": {},
            }
        )
        ingestor.fastf1 = _ExplodingFastF1()

        self.assertEqual(ingestor.ingest_session(2026, "Monaco Grand Prix", "R"), "2026-08-r")


class _FakeStorage:
    def __init__(self, artifacts: dict[str, Any]) -> None:
        self.artifacts = artifacts

    def exists(self, path: str) -> bool:
        return str(path) in self.artifacts

    def read_json(self, path: str) -> Any:
        return self.artifacts[str(path)]


class _ExplodingFastF1:
    def load_session(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("FastF1 must not be loaded when the dataset already exists")


def _ingestor(artifacts: dict[str, Any]) -> FastF1Ingestor:
    # Bypass __init__ so the test does not depend on settings or a data root.
    ingestor = FastF1Ingestor.__new__(FastF1Ingestor)
    ingestor.storage = _FakeStorage(artifacts)
    return ingestor


if __name__ == "__main__":
    unittest.main()
