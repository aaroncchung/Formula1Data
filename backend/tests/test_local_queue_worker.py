from __future__ import annotations

import os
import sys
import tempfile
import time
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
    merge_incremental_indexes,
    merge_season,
    process_message,
    session_artifacts_exist,
    sync_artifacts_to_r2,
    upload_r2_object,
    verify_remote_manifest,
)
from pipeline import local_queue_worker
from pipeline.artifacts import checksum_file, read_json, write_json


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
                # upload_r2_object inspects returncode, so the mock has to look
                # like a completed process rather than a bare MagicMock.
                run.return_value.returncode = 0
                run.return_value.stdout = ""
                run.return_value.stderr = ""
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

    def _build_session_tree(self, output_dir, body_count):
        session_dir = output_dir / "sessions" / "2025-09-r"
        (session_dir / "telemetry").mkdir(parents=True, exist_ok=True)
        for index in range(body_count):
            (session_dir / "telemetry" / f"ver-lap-{index}.json").write_text("{}", encoding="utf-8")
        (session_dir / "manifest.json").write_text("{}", encoding="utf-8")
        (output_dir / "seasons").mkdir(parents=True, exist_ok=True)
        (output_dir / "seasons" / "2025.json").write_text("{}", encoding="utf-8")
        (output_dir / "catalog.json").write_text("{}", encoding="utf-8")

    MARKER_KEYS = [
        "test-bucket/sessions/2025-09-r/manifest.json",
        "test-bucket/seasons/2025.json",
        "test-bucket/catalog.json",
    ]

    def test_r2_sync_uploads_bodies_concurrently(self):
        """A serial implementation cannot satisfy the barrier and would fail."""
        import threading
        from types import SimpleNamespace

        workers = 4
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            self._build_session_tree(output_dir, body_count=workers * 2)

            barrier = threading.Barrier(workers, timeout=10)

            def fake_run(args, **kwargs):
                if "telemetry" in args[4]:
                    # Blocks until `workers` bodies are in flight together.
                    barrier.wait()
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.dict(os.environ, {"R2_UPLOAD_CONCURRENCY": str(workers)}):
                with patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"):
                    with patch(
                        "pipeline.local_queue_worker.subprocess.run", side_effect=fake_run
                    ):
                        sync_artifacts_to_r2(
                            output_dir, "test-bucket", session_id="2025-09-r", year=2025
                        )

    def test_r2_sync_finishes_every_body_before_starting_any_commit_marker(self):
        """Markers must follow body completion, not merely body submission."""
        import threading
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            self._build_session_tree(output_dir, body_count=12)

            lock = threading.Lock()
            body_finished = []
            marker_started = []

            def fake_run(args, **kwargs):
                key = args[4]
                if "telemetry" in key:
                    time.sleep(0.02)
                    with lock:
                        body_finished.append(time.perf_counter())
                else:
                    with lock:
                        marker_started.append((time.perf_counter(), key))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"):
                with patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run):
                    sync_artifacts_to_r2(
                        output_dir, "test-bucket", session_id="2025-09-r", year=2025
                    )

            self.assertEqual(len(body_finished), 12)
            self.assertEqual([key for _, key in marker_started], self.MARKER_KEYS)
            # Every body completed before the first marker was even started.
            self.assertLess(max(body_finished), marker_started[0][0])

    def test_r2_sync_skips_commit_markers_when_a_body_upload_fails(self):
        """A failed body must never be followed by a marker claiming completeness."""
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            self._build_session_tree(output_dir, body_count=10)

            attempted = []

            def fake_run(args, **kwargs):
                key = args[4]
                attempted.append(key)
                if key.endswith("ver-lap-3.json"):
                    return SimpleNamespace(returncode=1, stdout="", stderr="boom")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run):
                # Skip the retry backoff so the test does not sleep. The pacer is
                # stubbed too: patching time.sleep alone would let it reserve
                # slots without ever waiting, mutating shared module state and
                # making this test order-dependent.
                with patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"):
                    with patch("pipeline.local_queue_worker.time.sleep"):
                        with self.assertRaises(RuntimeError):
                            sync_artifacts_to_r2(
                                output_dir, "test-bucket", session_id="2025-09-r", year=2025
                            )

            for marker in self.MARKER_KEYS:
                self.assertNotIn(marker, attempted)

    def test_upload_retries_with_backoff_then_succeeds(self):
        from types import SimpleNamespace

        results = [
            SimpleNamespace(returncode=1, stdout="", stderr="transient"),
            SimpleNamespace(returncode=1, stdout="", stderr="transient"),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        ]

        with patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"):
            with patch("pipeline.local_queue_worker.time.sleep") as sleep:
                with patch(
                    "pipeline.local_queue_worker.subprocess.run", side_effect=results
                ) as run:
                    upload_r2_object(Path("body.json"), "test-bucket", "key.json")

        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])

    def test_upload_backs_off_far_longer_when_throttled(self):
        """A rate-limit response must not be retried on a seconds-scale delay."""
        from types import SimpleNamespace

        throttled = SimpleNamespace(returncode=1, stdout="", stderr="Error 429: rate limit exceeded")

        with patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"):
            with patch("pipeline.local_queue_worker.time.sleep") as sleep:
                with patch(
                    "pipeline.local_queue_worker.subprocess.run",
                    side_effect=[throttled, SimpleNamespace(returncode=0, stdout="", stderr="")],
                ):
                    upload_r2_object(Path("body.json"), "test-bucket", "key.json")

        self.assertEqual([call.args[0] for call in sleep.call_args_list], [60])

    def test_request_pacer_spaces_starts_across_threads(self):
        """The point of the pacer is cross-thread spacing, so assert that.

        A sequential-only assertion would still pass an implementation that
        dropped its lock or let concurrent callers cluster into one slot.
        """
        import threading

        per_second = 100.0
        interval = 1.0 / per_second
        calls = 20
        pacer = local_queue_worker._RequestPacer(per_second=per_second)

        starts = []
        lock = threading.Lock()

        def worker():
            pacer.acquire()
            with lock:
                starts.append(time.perf_counter())

        threads = [threading.Thread(target=worker) for _ in range(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(len(starts), calls)
        starts.sort()
        gaps = [later - earlier for earlier, later in zip(starts, starts[1:])]
        # perf_counter, not monotonic: this asserts a 10ms spacing, and
        # time.monotonic() is GetTickCount64() on Windows with a 15.625ms
        # resolution -- coarser than the interval being measured, so
        # concurrent starts read as identical and min(gaps) is 0.0.
        # perf_counter is QueryPerformanceCounter there (~100ns).
        #
        # Generous factors: this asserts starts are spaced at all, without
        # becoming flaky when a loaded CI runner deschedules a thread.
        self.assertGreaterEqual(min(gaps), interval * 0.5)
        self.assertGreaterEqual(starts[-1] - starts[0], interval * (calls - 1) * 0.8)

    def test_request_pacer_is_disabled_when_rate_is_zero(self):
        pacer = local_queue_worker._RequestPacer(per_second=0)
        started = time.perf_counter()
        for _ in range(50):
            pacer.acquire()
        self.assertLess(time.perf_counter() - started, 0.5)

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

    def test_r2_hydration_bootstraps_a_bucket_with_no_catalog(self):
        """The first ingestion into a fresh bucket has nothing to hydrate."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "existing"
            with patch("pipeline.local_queue_worker.subprocess.run") as run:
                run.return_value.returncode = 1
                run.return_value.stderr = "The specified key does not exist."
                run.return_value.stdout = ""

                hydrate_r2_indexes(destination, "test-bucket", "", 2026)

            self.assertFalse((destination / "catalog.json").exists())

            # The merge then no-ops, so the freshly built catalog is published
            # exactly as built: one season, one session.
            publication_dir = root / "data"
            catalog = {
                "schema_version": 1,
                "seasons": [{"year": 2026}],
                "meetings": [{"meeting_id": "2026-09-x", "year": 2026, "round": 9}],
                "sessions": [{"session_id": "2026-09-r", "year": 2026, "round": 9, "type": "R"}],
            }
            write_json(publication_dir / "catalog.json", catalog)
            merge_incremental_indexes(destination, publication_dir, 2026)

            self.assertEqual(read_json(publication_dir / "catalog.json"), catalog)

    def test_r2_hydration_still_requires_a_season_index_the_catalog_claims(self):
        """Bootstrap tolerance must not extend to an index known to exist."""
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "existing"

            def fake_run(args, **kwargs):
                if args[4].endswith("catalog.json"):
                    write_json(Path(args[6]), {"seasons": [{"year": 2026}]})
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                return SimpleNamespace(returncode=1, stdout="", stderr="object not found")

            with patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "required R2 index seasons/2026.json"):
                    hydrate_r2_indexes(destination, "test-bucket", "", 2026)

    def test_reused_session_publishes_merged_r2_indexes(self):
        """Reuse uploads the session; without the indexes nothing can find it."""
        session_id = "2026-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "data"
            session_dir = output_dir / "sessions" / session_id
            summary_path = session_dir / "summary.json"
            write_json(summary_path, {"session_id": session_id})
            write_json(
                session_dir / "manifest.json",
                {
                    "session_id": session_id,
                    "generated_at": "2026-07-13T12:00:00Z",
                    "sections": [
                        {
                            "kind": "summary",
                            "path": f"sessions/{session_id}/summary.json",
                            "size_bytes": summary_path.stat().st_size,
                            "checksum": checksum_file(summary_path),
                        }
                    ],
                },
            )
            local_rows = {
                "meetings": [{"meeting_id": "2026-09-x", "year": 2026, "round": 9}],
                "sessions": [{"session_id": session_id, "year": 2026, "round": 9, "type": "R"}],
            }
            write_json(
                output_dir / "catalog.json",
                {"schema_version": 1, "seasons": [{"year": 2026}], **local_rows},
            )
            write_json(
                output_dir / "seasons" / "2026.json",
                {"schema_version": 1, "season": {"year": 2026}, **local_rows},
            )

            remote_rows = {
                "meetings": [{"meeting_id": "2026-08-w", "year": 2026, "round": 8}],
                "sessions": [{"session_id": "2026-08-r", "year": 2026, "round": 8, "type": "R"}],
            }
            remote_catalog = {"schema_version": 1, "seasons": [{"year": 2026}], **remote_rows}
            remote_season = {"schema_version": 1, "season": {"year": 2026}, **remote_rows}

            def fake_download(_bucket, key, destination, **_kwargs):
                write_json(destination, remote_catalog if "catalog" in key else remote_season)
                return True

            uploaded: dict[str, object] = {}

            def fake_upload(path, _bucket, key):
                uploaded[key] = read_json(path)

            with (
                patch.dict(os.environ, {}),
                patch(
                    "pipeline.local_queue_worker.download_r2_object", side_effect=fake_download
                ),
                patch("pipeline.local_queue_worker.upload_r2_object", side_effect=fake_upload),
                patch("pipeline.local_queue_worker.verify_remote_manifest"),
            ):
                result = process_message(
                    {
                        "job_id": "job-1",
                        "kind": "ingest_session",
                        "year": 2026,
                        "round": 9,
                        "session": "R",
                    },
                    data_dir=Path(temporary_directory) / "backend-data",
                    output_dir=output_dir,
                    artifact_destination="r2",
                    r2_bucket="test-bucket",
                )

            self.assertEqual(result["session_id"], session_id)
            self.assertIn(f"sessions/{session_id}/manifest.json", uploaded)
            self.assertIn("catalog.json", uploaded)
            self.assertIn("seasons/2026.json", uploaded)
            # The republished indexes carry both the reused session and the
            # sessions R2 already knew about.
            self.assertEqual(
                {row["session_id"] for row in uploaded["catalog.json"]["sessions"]},
                {"2026-08-r", session_id},
            )
            self.assertEqual(
                {row["session_id"] for row in uploaded["seasons/2026.json"]["sessions"]},
                {"2026-08-r", session_id},
            )

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
