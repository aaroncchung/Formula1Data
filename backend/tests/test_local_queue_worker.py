from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.local_queue_worker import expected_session_id, session_artifacts_exist


class LocalQueueWorkerTests(unittest.TestCase):
    def test_expected_session_id_prefers_message_value(self):
        self.assertEqual(
            expected_session_id({"session_id": "2025-01-r", "year": 2025, "round": 1, "session": "R"}),
            "2025-01-r",
        )

    def test_expected_session_id_can_be_derived(self):
        self.assertEqual(
            expected_session_id({"year": 2025, "round": 9, "session": "R"}),
            "2025-09-r",
        )

    def test_session_artifacts_exist_checks_manifest(self):
        self.assertFalse(session_artifacts_exist(Path("missing-output"), "2025-09-r"))


if __name__ == "__main__":
    unittest.main()
