from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.local_queue_worker import expected_session_id, session_artifacts_exist, sync_artifacts_to_r2


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

    def test_r2_sync_uploads_only_affected_catalog_season_and_session(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            paths = [
                output_dir / "catalog.json",
                output_dir / "seasons" / "2025.json",
                output_dir / "seasons" / "2024.json",
                output_dir / "sessions" / "2025-09-r" / "manifest.json",
                output_dir / "sessions" / "2025-08-r" / "manifest.json",
            ]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

            with patch("pipeline.local_queue_worker.subprocess.run") as run:
                sync_artifacts_to_r2(
                    output_dir,
                    "test-bucket",
                    "prod/data",
                    session_id="2025-09-r",
                    year=2025,
                )

            uploaded = {call.args[0][6] for call in run.call_args_list}
            self.assertEqual(
                uploaded,
                {
                    str(output_dir / "catalog.json"),
                    str(output_dir / "seasons" / "2025.json"),
                    str(output_dir / "sessions" / "2025-09-r" / "manifest.json"),
                },
            )
            object_keys = {call.args[0][4] for call in run.call_args_list}
            self.assertEqual(
                object_keys,
                {
                    "test-bucket/prod/data/catalog.json",
                    "test-bucket/prod/data/seasons/2025.json",
                    "test-bucket/prod/data/sessions/2025-09-r/manifest.json",
                },
            )


if __name__ == "__main__":
    unittest.main()
