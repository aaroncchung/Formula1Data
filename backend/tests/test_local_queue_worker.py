from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.local_queue_worker import (
    build_success_payload,
    callback_job_status,
    expected_session_id,
    hydrate_r2_indexes,
    merge_catalog,
    merge_season,
    session_artifacts_exist,
    sync_artifacts_to_r2,
    verify_remote_manifest,
)
from pipeline.artifacts import checksum_file, write_json


class LocalQueueWorkerTests(unittest.TestCase):
    def test_callback_includes_access_service_token_headers(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with (
            patch.dict(
                os.environ,
                {
                    "CF_ACCESS_CLIENT_ID": "access-id",
                    "CF_ACCESS_CLIENT_SECRET": "access-secret",
                },
            ),
            patch(
                "pipeline.local_queue_worker.urllib.request.urlopen", return_value=response
            ) as open_url,
        ):
            callback_job_status(
                "https://worker.example",
                "callback-token",
                "job-id",
                {"status": "running"},
            )

        headers = dict(open_url.call_args.args[0].header_items())
        self.assertEqual(headers["Authorization"], "Bearer callback-token")
        self.assertEqual(headers["Cf-access-client-id"], "access-id")
        self.assertEqual(headers["Cf-access-client-secret"], "access-secret")

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

            ordered_keys = [call.args[0][4] for call in run.call_args_list]
            self.assertEqual(ordered_keys[-2:], ["test-bucket/prod/data/seasons/2025.json", "test-bucket/prod/data/catalog.json"])

    def test_catalog_merge_preserves_existing_sessions_and_recomputes_totals(self):
        existing = {
            "schema_version": 1,
            "generated_at": "old",
            "source": {"mode": "processed", "files": ["old.json"]},
            "seasons": [{"year": 2025, "meeting_count": 2, "ingested_meeting_count": 1}],
            "meetings": [
                {"meeting_id": "2025-01-a", "year": 2025, "round": 1, "is_ingested": True},
                {"meeting_id": "2025-02-b", "year": 2025, "round": 2, "is_ingested": False},
            ],
            "sessions": [{"session_id": "2025-01-r", "year": 2025, "round": 1, "type": "R"}],
        }
        incoming = {
            "schema_version": 1,
            "generated_at": "new",
            "source": {"mode": "processed", "files": ["new.json"]},
            "seasons": [{"year": 2025, "meeting_count": 1, "ingested_meeting_count": 1}],
            "meetings": [
                {"meeting_id": "2025-02-b", "year": 2025, "round": 2, "is_ingested": True}
            ],
            "sessions": [{"session_id": "2025-02-r", "year": 2025, "round": 2, "type": "R"}],
        }

        merged = merge_catalog(existing, incoming)

        self.assertEqual([row["session_id"] for row in merged["sessions"]], ["2025-01-r", "2025-02-r"])
        self.assertEqual(merged["totals"], {"seasons": 1, "meetings": 2, "sessions": 2})
        self.assertEqual(merged["seasons"][0]["meeting_count"], 2)
        self.assertEqual(merged["seasons"][0]["ingested_meeting_count"], 2)
        self.assertEqual(merged["source"]["files"], ["old.json", "new.json"])

    def test_season_merge_keeps_schedule_and_adds_new_session(self):
        existing = {
            "schema_version": 1,
            "generated_at": "old",
            "season": {"year": 2026, "meeting_count": 2, "ingested_meeting_count": 1},
            "meetings": [
                {"meeting_id": "2026-01-a", "year": 2026, "round": 1, "is_ingested": True},
                {"meeting_id": "2026-02-b", "year": 2026, "round": 2, "is_ingested": False},
            ],
            "sessions": [{"session_id": "2026-01-r", "year": 2026, "round": 1, "type": "R"}],
        }
        incoming = {
            "schema_version": 1,
            "generated_at": "new",
            "season": {"year": 2026, "meeting_count": 1, "ingested_meeting_count": 1},
            "meetings": [
                {"meeting_id": "2026-02-b", "year": 2026, "round": 2, "is_ingested": True}
            ],
            "sessions": [{"session_id": "2026-02-r", "year": 2026, "round": 2, "type": "R"}],
        }

        merged = merge_season(existing, incoming)

        self.assertEqual(len(merged["meetings"]), 2)
        self.assertEqual(len(merged["sessions"]), 2)
        self.assertEqual(merged["season"]["meeting_count"], 2)
        self.assertEqual(merged["season"]["ingested_meeting_count"], 2)

    def test_r2_hydration_requires_the_current_catalog(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory)
            with patch("pipeline.local_queue_worker.subprocess.run") as run:
                run.return_value.returncode = 1
                run.return_value.stderr = "object not found"
                run.return_value.stdout = ""

                with self.assertRaisesRegex(RuntimeError, "required R2 index catalog.json"):
                    hydrate_r2_indexes(destination, "test-bucket", "", 2026)

    def test_hundreds_of_telemetry_laps_use_a_compact_manifest_callback(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            session_id = "2026-09-r"
            session_dir = output_dir / "sessions" / session_id
            summary_path = session_dir / "summary.json"
            telemetry_index_path = session_dir / "telemetry" / "index.json"
            write_json(summary_path, {"session_id": session_id})
            write_json(telemetry_index_path, {"session_id": session_id, "laps": []})
            sections = [
                {
                    "kind": "summary",
                    "path": f"sessions/{session_id}/summary.json",
                    "size_bytes": summary_path.stat().st_size,
                    "checksum": checksum_file(summary_path),
                },
                {
                    "kind": "telemetry-index",
                    "path": f"sessions/{session_id}/telemetry/index.json",
                    "size_bytes": telemetry_index_path.stat().st_size,
                    "checksum": checksum_file(telemetry_index_path),
                },
            ]
            for lap in range(500):
                sections.append(
                    {
                        "kind": "telemetry-lap",
                        "path": f"sessions/{session_id}/telemetry/driver-lap-{lap + 1}.json",
                        "size_bytes": 100,
                        "checksum": f"sha256:{lap:064x}",
                    }
                )
            write_json(
                session_dir / "manifest.json",
                {
                    "session_id": session_id,
                    "generated_at": "2026-07-13T12:00:00Z",
                    "sections": sections,
                    "telemetry": {
                        "lap_count": 500,
                        "sample_count": 100000,
                        "max_samples_per_lap": 300,
                    },
                },
            )

            payload = build_success_payload(output_dir, session_id, "2026-07-13T12:00:00Z")

            self.assertEqual(payload["manifest"]["kind"], "manifest")
            self.assertEqual(len(payload["artifacts"]), 2)
            telemetry = next(
                artifact
                for artifact in payload["artifacts"]
                if artifact["kind"] == "telemetry-index"
            )
            self.assertEqual(telemetry["metadata"]["lap_file_count"], 500)

    def test_remote_manifest_is_compared_to_the_published_manifest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            session_id = "2026-09-r"
            manifest_path = output_dir / "sessions" / session_id / "manifest.json"
            write_json(manifest_path, {"session_id": session_id, "sections": []})

            def download(_bucket, _key, destination, **_kwargs):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(manifest_path.read_bytes())
                return True

            with patch("pipeline.local_queue_worker.download_r2_object", side_effect=download):
                manifest = verify_remote_manifest(output_dir, "bucket", "", session_id)

            self.assertEqual(manifest["session_id"], session_id)


if __name__ == "__main__":
    unittest.main()
