from __future__ import annotations

import json
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
                    # First publication: no remote manifest, so no rollback
                    # backup is taken and every wrangler call here is an upload.
                    with patch(
                        "pipeline.local_queue_worker.download_r2_object", return_value=False
                    ):
                        with patch(
                            "pipeline.local_queue_worker.subprocess.run", side_effect=fake_run
                        ):
                            sync_artifacts_to_r2(
                                output_dir,
                                "test-bucket",
                                session_id="2025-09-r",
                                year=2025,
                                allow_missing_catalog=True,
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
                # First publication, so the rollback backup is skipped and the
                # only wrangler calls are the uploads this test times.
                with patch("pipeline.local_queue_worker.download_r2_object", return_value=False):
                    with patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run):
                        sync_artifacts_to_r2(
                            output_dir,
                            "test-bucket",
                            session_id="2025-09-r",
                            year=2025,
                            allow_missing_catalog=True,
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
                    # First publication: nothing published yet, so nothing is
                    # backed up and nothing is rolled back. The refresh case is
                    # covered by the rollback tests below.
                    with patch(
                        "pipeline.local_queue_worker.download_r2_object", return_value=False
                    ):
                        with patch("pipeline.local_queue_worker.time.sleep"):
                            with self.assertRaises(RuntimeError):
                                sync_artifacts_to_r2(
                                    output_dir,
                                    "test-bucket",
                                    session_id="2025-09-r",
                                    year=2025,
                                    allow_missing_catalog=True,
                                )

            for marker in self.MARKER_KEYS:
                self.assertNotIn(marker, attempted)

    def _write_generation(self, output_dir, session_id, body_count, tag, extra=()):
        """Write one whole generation of a session and return its object keys.

        The manifest enumerates every body in `sections`, exactly as a real one
        does, because that list is what the rollback guard reads to learn which
        objects the live generation actually owns.
        """
        session_dir = output_dir / "sessions" / session_id
        (session_dir / "telemetry").mkdir(parents=True, exist_ok=True)
        keys = []
        for index in range(body_count):
            key = f"sessions/{session_id}/telemetry/ver-lap-{index}.json"
            (output_dir / key).write_text(
                f'{{"generation": "{tag}", "lap": {index}}}', encoding="utf-8"
            )
            keys.append(key)
        for relative in extra:
            key = f"sessions/{session_id}/{relative}"
            path = output_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'{{"generation": "{tag}"}}', encoding="utf-8")
            keys.append(key)
        manifest_key = f"sessions/{session_id}/manifest.json"
        (output_dir / manifest_key).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "session_id": session_id,
                    "generation": tag,
                    "sections": [{"kind": "body", "path": key} for key in sorted(keys)],
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "seasons").mkdir(parents=True, exist_ok=True)
        (output_dir / "seasons" / "2025.json").write_text(
            f'{{"generation": "{tag}"}}', encoding="utf-8"
        )
        (output_dir / "catalog.json").write_text(f'{{"generation": "{tag}"}}', encoding="utf-8")
        return keys + [manifest_key]

    def _fake_r2(self, remote, put_fails=None, get_fails=None):
        """A stand-in bucket: `remote` maps object key to stored bytes.

        Returns the `subprocess.run` side effect and the list of (verb, key)
        wrangler calls it saw, so tests can assert on operation counts as well
        as on the bucket's final contents.

        `get_fails(key, seen)` makes a read of an object that *does* exist fail
        the way an operational fault does -- a network drop, an expired token, a
        wrangler crash -- which is the case that must never be mistaken for the
        object being absent.
        """
        import threading
        from types import SimpleNamespace

        calls = []
        lock = threading.Lock()

        def fake_run(args, **kwargs):
            verb = args[3]
            key = args[4].split("/", 1)[1]
            with lock:
                calls.append((verb, key))
                seen = sum(1 for call in calls if call == (verb, key))
            if verb == "delete":
                # R2 deletes are idempotent: removing a key that is not there
                # succeeds, which is what makes the rollback sweep safe.
                with lock:
                    remote.pop(key, None)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            file_path = Path(args[6])
            if verb == "put":
                if put_fails and put_fails(key, seen):
                    return SimpleNamespace(returncode=1, stdout="", stderr="upload failed")
                with lock:
                    remote[key] = file_path.read_bytes()
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if get_fails and get_fails(key, seen):
                # Deliberately not a "does not exist" message: wrangler reports
                # an operational failure with entirely different, unstable text.
                return SimpleNamespace(
                    returncode=1, stdout="", stderr="A request to the Cloudflare API failed."
                )
            with lock:
                body = remote.get(key)
            if body is None:
                return SimpleNamespace(
                    returncode=1, stdout="", stderr="The specified key does not exist."
                )
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(body)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        return fake_run, calls

    def test_a_failed_refresh_restores_the_previously_published_bodies(self):
        """F-02: a part-way failure must not leave a mix of two generations live.

        Bodies go to the same keys as the live generation, and nothing on the
        read path checksums a section, so an unrestored mixture is served
        silently under a manifest that no longer describes it.
        """
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_dir = root / "old"
            new_dir = root / "new"
            published = self._write_generation(old_dir, session_id, 6, "old")
            self._write_generation(new_dir, session_id, 6, "new")
            remote = {key: (old_dir / key).read_bytes() for key in published}
            before = dict(remote)

            def put_fails(key, seen):
                # Three PUTs of this key is the whole retry budget, so the
                # refresh gives up on it. The fourth is the rollback putting the
                # old bytes back, and that one is allowed through -- the point of
                # this test is the rollback's effect, not its error path.
                return key.endswith("ver-lap-3.json") and seen <= 3

            fake_run, _calls = self._fake_r2(remote, put_fails)
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaises(RuntimeError):
                    sync_artifacts_to_r2(
                        new_dir, "test-bucket", session_id=session_id, year=2025
                    )

            # Byte-for-byte what was live before the refresh started.
            self.assertEqual(remote, before)
            self.assertNotIn("seasons/2025.json", remote)
            self.assertNotIn("catalog.json", remote)

    def _season_index(self, session_ids):
        return json.dumps(
            {"season": 2025, "sessions": [{"session_id": value} for value in session_ids]}
        ).encode("utf-8")

    def test_a_refresh_stops_when_the_published_manifest_cannot_be_read(self):
        """An unreadable manifest is not an absent one.

        A GET that exhausts its retries against a live object looks exactly like
        a GET against a key that was never there. Believing the second reading
        skips the backup and overwrites a generation that cannot be restored.
        """
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_dir = root / "old"
            new_dir = root / "new"
            published = self._write_generation(old_dir, session_id, 4, "old")
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {key: (old_dir / key).read_bytes() for key in published}
            # The indexes read cleanly and say the session is published, so the
            # unreadable manifest cannot be explained away as a new session.
            remote["catalog.json"] = json.dumps({"seasons": [{"year": 2025}]}).encode("utf-8")
            remote["seasons/2025.json"] = self._season_index([session_id])
            before = dict(remote)

            fake_run, calls = self._fake_r2(
                remote, get_fails=lambda key, seen: key.endswith(f"{session_id}/manifest.json")
            )
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaisesRegex(RuntimeError, "manifest"):
                    sync_artifacts_to_r2(
                        new_dir, "test-bucket", session_id=session_id, year=2025
                    )

            # Nothing was written at all: the refresh stopped before it could
            # damage anything, rather than stopping half way through.
            self.assertEqual(remote, before)
            self.assertEqual([key for verb, key in calls if verb == "put"], [])

    def test_a_refresh_stops_when_a_published_body_cannot_be_backed_up(self):
        """A backup missing one live object is not a backup.

        Without every object it is about to overwrite, a rollback can only put
        part of the old generation back -- which is the mixed generation this
        whole guard exists to prevent.
        """
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_dir = root / "old"
            new_dir = root / "new"
            published = self._write_generation(old_dir, session_id, 4, "old")
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {key: (old_dir / key).read_bytes() for key in published}
            before = dict(remote)

            fake_run, calls = self._fake_r2(
                remote, get_fails=lambda key, seen: key.endswith("ver-lap-2.json")
            )
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaisesRegex(RuntimeError, "ver-lap-2.json"):
                    sync_artifacts_to_r2(
                        new_dir, "test-bucket", session_id=session_id, year=2025
                    )

            self.assertEqual(remote, before)
            self.assertEqual([key for verb, key in calls if verb == "put"], [])

    def test_a_rollback_removes_objects_only_the_new_generation_had(self):
        """A surviving new-only object is a mixed generation the manifest hides.

        The frontend reads analysis artifacts from fixed paths -- it never
        consults the manifest as an index -- so an object left behind by a
        failed refresh is served next to the restored old generation.
        """
        session_id = "2025-09-r"
        new_only = "analysis/pace-prediction.json"
        # Under a prefix, so the manifest's data-root-relative section paths and
        # the body keys have to be composed into object keys the same way.
        prefix = "prod/data"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_dir = root / "old"
            new_dir = root / "new"
            published = self._write_generation(old_dir, session_id, 4, "old")
            self._write_generation(new_dir, session_id, 4, "new", extra=[new_only])
            remote = {f"{prefix}/{key}": (old_dir / key).read_bytes() for key in published}
            before = dict(remote)

            # Serial uploads so the new-only object is certain to have landed
            # before the failure: `analysis/` sorts ahead of `telemetry/`.
            fake_run, calls = self._fake_r2(
                remote, put_fails=lambda key, seen: key.endswith("ver-lap-3.json") and seen <= 3
            )
            with (
                patch.dict(os.environ, {"R2_UPLOAD_CONCURRENCY": "1"}),
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaises(RuntimeError):
                    sync_artifacts_to_r2(
                        new_dir, "test-bucket", prefix, session_id=session_id, year=2025
                    )

            new_only_key = f"{prefix}/sessions/{session_id}/{new_only}"
            uploaded = [key for verb, key in calls if verb == "put"]
            self.assertIn(new_only_key, uploaded)
            self.assertIn(new_only_key, [key for verb, key in calls if verb == "delete"])
            # The whole remotely visible object set, not just the old keys.
            self.assertEqual(remote, before)

    def _catalog(self, years):
        return json.dumps({"seasons": [{"year": year} for year in years]}).encode("utf-8")

    def _urlopen_status(self, status):
        """A stand-in for the Worker's HEAD /data/... existence probe."""
        import urllib.error

        def fake_urlopen(request, timeout=None):
            if status == 404:
                raise urllib.error.HTTPError(
                    request.full_url, 404, "Not Found", {}, None
                )
            if status >= 500:
                raise urllib.error.HTTPError(
                    request.full_url, status, "Server Error", {}, None
                )
            response = MagicMock()
            response.status = status
            response.__enter__.return_value = response
            return response

        return fake_urlopen

    def test_a_published_manifest_is_not_overwritten_when_the_season_marker_lagged(self):
        """Case A: the manifest is live but the season index never listed it.

        A run that published bodies and the manifest and then failed on the
        season index leaves exactly this state. Reading "not in the index" as
        "never published" here would overwrite a live generation with no backup.
        """
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_dir = root / "old"
            new_dir = root / "new"
            published = self._write_generation(old_dir, session_id, 4, "old")
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {key: (old_dir / key).read_bytes() for key in published}
            remote["catalog.json"] = self._catalog([2025])
            # The marker that never landed: the session is missing from it.
            remote["seasons/2025.json"] = self._season_index(["2025-08-r"])
            before = dict(remote)

            fake_run, calls = self._fake_r2(
                remote, get_fails=lambda key, seen: key.endswith(f"{session_id}/manifest.json")
            )
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
                patch(
                    "pipeline.local_queue_worker.urllib.request.urlopen",
                    side_effect=self._urlopen_status(200),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "manifest"):
                    sync_artifacts_to_r2(
                        new_dir,
                        "test-bucket",
                        session_id=session_id,
                        year=2025,
                        probe_base_url="https://worker.example",
                    )

            self.assertEqual([key for verb, key in calls if verb == "put"], [])
            self.assertEqual(remote, before)

    def test_a_published_manifest_is_not_overwritten_when_the_catalog_marker_lagged(self):
        """Case B: first session of a new year whose catalog PUT never landed.

        The season index carries the session, so consulting it is what keeps the
        catalog's silence about the year from being read as proof of absence.
        """
        session_id = "2026-01-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_dir = root / "old"
            new_dir = root / "new"
            published = self._write_generation(old_dir, session_id, 4, "old")
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {key: (old_dir / key).read_bytes() for key in published}
            # The catalog reads cleanly and simply has not heard of 2026 yet.
            remote["catalog.json"] = self._catalog([2025])
            remote["seasons/2026.json"] = self._season_index([session_id])
            before = dict(remote)

            fake_run, calls = self._fake_r2(
                remote, get_fails=lambda key, seen: key.endswith(f"{session_id}/manifest.json")
            )
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaisesRegex(RuntimeError, "manifest"):
                    sync_artifacts_to_r2(
                        new_dir, "test-bucket", session_id=session_id, year=2026
                    )

            self.assertEqual([key for verb, key in calls if verb == "put"], [])
            self.assertEqual(remote, before)

    def test_a_failed_commit_marker_withdraws_the_manifest_it_just_published(self):
        """A live manifest the indexes do not list defeats existence detection.

        Leaving it is what creates Case A, so a marker failure takes it back
        and keeps "absent from the indexes" and "no live generation" the same
        statement.
        """
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            new_dir = Path(temporary_directory) / "new"
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {
                "catalog.json": self._catalog([2025]),
                "seasons/2025.json": self._season_index(["2025-08-r"]),
            }

            fake_run, calls = self._fake_r2(
                remote, put_fails=lambda key, seen: key == "seasons/2025.json"
            )
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaises(RuntimeError):
                    sync_artifacts_to_r2(
                        new_dir, "test-bucket", session_id=session_id, year=2025
                    )

            manifest_key = f"sessions/{session_id}/manifest.json"
            self.assertIn(manifest_key, [key for verb, key in calls if verb == "put"])
            # Published, then taken back: nothing claims the bodies now.
            self.assertIn(manifest_key, [key for verb, key in calls if verb == "delete"])
            self.assertNotIn(manifest_key, remote)

    def test_an_unreadable_season_index_is_not_proof_the_session_is_absent(self):
        """An index that will not read cannot corroborate anything."""
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            new_dir = root / "new"
            old_dir = root / "old"
            published = self._write_generation(old_dir, session_id, 4, "old")
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {key: (old_dir / key).read_bytes() for key in published}
            remote["catalog.json"] = self._catalog([2025])
            remote["seasons/2025.json"] = self._season_index(["2025-08-r"])

            fake_run, calls = self._fake_r2(
                remote,
                get_fails=lambda key, seen: key.endswith(f"{session_id}/manifest.json")
                or key == "seasons/2025.json",
            )
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaises(RuntimeError):
                    sync_artifacts_to_r2(
                        new_dir, "test-bucket", session_id=session_id, year=2025
                    )

            self.assertEqual([key for verb, key in calls if verb == "put"], [])

    def test_the_first_session_of_a_new_year_still_publishes(self):
        """The legitimate shape of Case B: nothing for this year exists yet."""
        session_id = "2026-01-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            new_dir = Path(temporary_directory) / "new"
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {"catalog.json": self._catalog([2025])}

            fake_run, calls = self._fake_r2(remote)
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                sync_artifacts_to_r2(new_dir, "test-bucket", session_id=session_id, year=2026)

            self.assertIn(f"sessions/{session_id}/manifest.json", remote)
            self.assertEqual([key for verb, key in calls if verb == "delete"], [])

    def test_a_probe_that_reports_the_manifest_absent_permits_a_first_publication(self):
        """A 404 is the positive proof of absence the indexes cannot give."""
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            new_dir = Path(temporary_directory) / "new"
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {
                "catalog.json": self._catalog([2025]),
                "seasons/2025.json": self._season_index(["2025-08-r"]),
            }

            fake_run, calls = self._fake_r2(remote)
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
                patch(
                    "pipeline.local_queue_worker.urllib.request.urlopen",
                    side_effect=self._urlopen_status(404),
                ),
            ):
                sync_artifacts_to_r2(
                    new_dir,
                    "test-bucket",
                    session_id=session_id,
                    year=2025,
                    probe_base_url="https://worker.example",
                )

            self.assertIn(f"sessions/{session_id}/manifest.json", remote)
            # A definitive 404 settles it without reading the indexes at all.
            self.assertNotIn("catalog.json", [key for verb, key in calls if verb == "get"])

    def test_a_successful_refresh_removes_a_section_the_new_generation_dropped(self):
        """A dropped section is served from the old generation until it is gone.

        `build_static_artifacts` writes a section only when the bundle carries
        it, and the frontend reads every section from a fixed path rather than
        through the manifest, so a leftover is read as current data.
        """
        session_id = "2025-09-r"
        dropped = "weather.json"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_dir = root / "old"
            new_dir = root / "new"
            published = self._write_generation(old_dir, session_id, 3, "old", extra=[dropped])
            # The refresh no longer produces weather.json.
            self._write_generation(new_dir, session_id, 3, "new")
            remote = {key: (old_dir / key).read_bytes() for key in published}

            fake_run, calls = self._fake_r2(remote)
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                sync_artifacts_to_r2(new_dir, "test-bucket", session_id=session_id, year=2025)

            dropped_key = f"sessions/{session_id}/{dropped}"
            self.assertIn(dropped_key, [key for verb, key in calls if verb == "delete"])
            self.assertNotIn(dropped_key, remote)
            # Only the superseded object went: everything this build wrote stays.
            for key in [f"sessions/{session_id}/telemetry/ver-lap-{i}.json" for i in range(3)]:
                self.assertEqual(remote[key], (new_dir / key).read_bytes())
            self.assertIn(f"sessions/{session_id}/manifest.json", remote)
            # And the removal happens only after the new generation is committed.
            operations = [(verb, key) for verb, key in calls if verb in {"put", "delete"}]
            self.assertLess(
                operations.index(("put", "catalog.json")),
                operations.index(("delete", dropped_key)),
            )

    def test_a_failed_rollback_names_the_session_it_may_have_left_inconsistent(self):
        """The one thing worse than a failed refresh is a silent failed rollback."""
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_dir = root / "old"
            new_dir = root / "new"
            published = self._write_generation(old_dir, session_id, 4, "old")
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {key: (old_dir / key).read_bytes() for key in published}

            fake_run, _calls = self._fake_r2(
                remote, lambda key, seen: key.endswith("ver-lap-2.json")
            )
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaisesRegex(RuntimeError, "2025-09-r may now be inconsistent"):
                    sync_artifacts_to_r2(
                        new_dir, "test-bucket", session_id=session_id, year=2025
                    )

    def test_a_first_publication_into_an_empty_bucket_does_not_pay_for_a_backup(self):
        """Nothing is published yet, so there is nothing to protect.

        An empty bucket is the one case where unreadable indexes may be read as
        absence, and it is the operator who says so with --allow-missing-catalog.
        """
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            new_dir = Path(temporary_directory) / "new"
            self._write_generation(new_dir, session_id, 6, "new")
            remote: dict[str, bytes] = {}

            fake_run, calls = self._fake_r2(remote)
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                sync_artifacts_to_r2(
                    new_dir,
                    "test-bucket",
                    session_id=session_id,
                    year=2025,
                    allow_missing_catalog=True,
                )

            gets = [key for verb, key in calls if verb == "get"]
            # The manifest probe and the catalog that corroborates it, and no
            # body: an absent generation costs nothing to protect.
            self.assertEqual(
                set(gets), {f"sessions/{session_id}/manifest.json", "catalog.json"}
            )
            # Each retried to its budget before absence is believed, per F-03.
            self.assertEqual(len(gets), 6)
            self.assertEqual(len([key for verb, key in calls if verb == "put"]), 9)
            self.assertIn("catalog.json", remote)

    def test_a_new_session_in_a_populated_bucket_needs_no_flag_and_no_backup(self):
        """The ordinary case: a bucket full of other sessions, this one new.

        The catalog reads cleanly and does not carry the session, which is what
        makes the unreadable manifest safe to read as a genuinely new session.
        """
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            new_dir = Path(temporary_directory) / "new"
            self._write_generation(new_dir, session_id, 4, "new")
            remote = {
                "catalog.json": json.dumps({"seasons": [{"year": 2025}]}).encode("utf-8"),
                "seasons/2025.json": self._season_index(["2025-08-r"]),
            }

            fake_run, calls = self._fake_r2(remote)
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                sync_artifacts_to_r2(new_dir, "test-bucket", session_id=session_id, year=2025)

            self.assertEqual(remote[f"sessions/{session_id}/manifest.json"],
                             (new_dir / f"sessions/{session_id}/manifest.json").read_bytes())
            # No body was ever downloaded: there was no generation to copy.
            self.assertEqual(
                [key for verb, key in calls if verb == "get" and "telemetry" in key], []
            )
            self.assertEqual([key for verb, key in calls if verb == "delete"], [])

    def test_a_successful_refresh_commits_the_new_generation_without_rolling_back(self):
        session_id = "2025-09-r"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            old_dir = root / "old"
            new_dir = root / "new"
            published = self._write_generation(old_dir, session_id, 6, "old")
            self._write_generation(new_dir, session_id, 6, "new")
            remote = {key: (old_dir / key).read_bytes() for key in published}

            fake_run, calls = self._fake_r2(remote)
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                sync_artifacts_to_r2(new_dir, "test-bucket", session_id=session_id, year=2025)

            for key in published:
                self.assertEqual(remote[key], (new_dir / key).read_bytes())
            # Commit markers published as before.
            self.assertIn("seasons/2025.json", remote)
            self.assertIn("catalog.json", remote)
            put_keys = [key for verb, key in calls if verb == "put"]
            # One PUT per object: a rollback would have re-uploaded the bodies.
            self.assertEqual(len(put_keys), 9)
            self.assertEqual(len(put_keys), len(set(put_keys)))
            # The backup itself costs one GET per body plus the manifest probe.
            self.assertEqual(len([key for verb, key in calls if verb == "get"]), 7)
            self.assertEqual([key for verb, key in calls if verb == "delete"], [])
            # Commit markers still land last and in order, after every body.
            self.assertEqual(
                put_keys[-3:],
                [
                    f"sessions/{session_id}/manifest.json",
                    "seasons/2025.json",
                    "catalog.json",
                ],
            )

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
        # perf_counter on both sides, deliberately. This asserts a 10ms
        # spacing, and time.monotonic() is GetTickCount64() on Windows with a
        # 15.625ms resolution. Measuring with it made concurrent starts read as
        # identical; scheduling with it made them genuinely cluster, because a
        # stale `now` shrinks the delay the pacer computes. The pacer therefore
        # reads perf_counter too -- with monotonic this assertion failed about
        # one run in six at 4.2ms.
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

    def test_r2_hydration_bootstraps_a_bucket_with_no_catalog_when_opted_in(self):
        """The first ingestion into a fresh bucket has nothing to hydrate.

        Bootstrap is reachable, but only deliberately: an absent catalog is
        tolerated under --allow-missing-catalog and nowhere else.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "existing"
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run") as run,
            ):
                run.return_value.returncode = 1
                run.return_value.stderr = "The specified key does not exist."
                run.return_value.stdout = ""

                hydrate_r2_indexes(
                    destination, "test-bucket", "", 2026, allow_missing_catalog=True
                )

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

    def test_r2_hydration_fails_loudly_when_the_catalog_cannot_be_read(self):
        """Without the opt-in, an unreadable catalog is an error, not a bootstrap.

        Wrangler exits non-zero for both "no such object" and "that read
        failed", so tolerating absence by default would let one transient
        failure republish a catalog holding only the session just ingested.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "existing"
            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run") as run,
            ):
                run.return_value.returncode = 1
                run.return_value.stderr = "The specified key does not exist."
                run.return_value.stdout = ""

                with self.assertRaisesRegex(RuntimeError, "required R2 index catalog.json"):
                    hydrate_r2_indexes(destination, "test-bucket", "", 2026)

    def test_a_transient_catalog_read_is_retried_before_it_counts_as_absence(self):
        """A blip on the catalog read must not erase the sessions R2 knows about."""
        from types import SimpleNamespace

        remote_rows = {
            "meetings": [{"meeting_id": "2026-08-w", "year": 2026, "round": 8}],
            "sessions": [{"session_id": "2026-08-r", "year": 2026, "round": 8, "type": "R"}],
        }
        remote_catalog = {"schema_version": 1, "seasons": [{"year": 2026}], **remote_rows}
        remote_season = {"schema_version": 1, "season": {"year": 2026}, **remote_rows}
        attempted: list[str] = []

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "existing"

            def fake_run(args, **kwargs):
                key = args[4]
                attempted.append(key)
                if key.endswith("catalog.json") and attempted.count(key) == 1:
                    return SimpleNamespace(returncode=1, stdout="", stderr="connection reset")
                body = remote_catalog if key.endswith("catalog.json") else remote_season
                write_json(Path(args[6]), body)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep") as sleep,
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                hydrate_r2_indexes(destination, "test-bucket", "", 2026)

            self.assertEqual([call.args[0] for call in sleep.call_args_list], [2])
            self.assertEqual(read_json(destination / "catalog.json"), remote_catalog)

            # The retry is what keeps the merge from no-opping, so assert the
            # published catalog still carries the pre-existing session.
            publication_dir = root / "data"
            write_json(
                publication_dir / "catalog.json",
                {
                    "schema_version": 1,
                    "seasons": [{"year": 2026}],
                    "meetings": [{"meeting_id": "2026-09-x", "year": 2026, "round": 9}],
                    "sessions": [
                        {"session_id": "2026-09-r", "year": 2026, "round": 9, "type": "R"}
                    ],
                },
            )
            merge_incremental_indexes(destination, publication_dir, 2026)

            self.assertEqual(
                {
                    row["session_id"]
                    for row in read_json(publication_dir / "catalog.json")["sessions"]
                },
                {"2026-08-r", "2026-09-r"},
            )

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

            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
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
                if key.endswith("manifest.json"):
                    # The session is already published, so the refresh reads its
                    # manifest to learn which objects it has to copy first.
                    write_json(
                        destination,
                        {
                            "session_id": session_id,
                            "sections": [
                                {"kind": "summary", "path": f"sessions/{session_id}/summary.json"}
                            ],
                        },
                    )
                    return True
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

    def test_an_unreadable_catalog_aborts_instead_of_republishing_one_session(self):
        """The failure mode this guards: a one-session catalog over a full one.

        The bucket does have a catalog; the read just fails. Treating that as
        an empty bucket would publish an index holding only this session and
        hide every other one from clients, silently, on every ingestion.

        The same unreadable catalog now also stops the refresh before it writes
        anything, because a catalog that cannot be read cannot confirm whether
        this session already has a published generation to protect.
        """
        from types import SimpleNamespace

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

            def fake_run(args, **kwargs):
                # Only downloads reach subprocess.run here; uploads are stubbed.
                return SimpleNamespace(returncode=1, stdout="", stderr="connection reset by peer")

            uploaded: dict[str, object] = {}

            def fake_upload(path, _bucket, key):
                uploaded[key] = read_json(path)

            with (
                patch.dict(os.environ, {}),
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker.time.sleep"),
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
                patch("pipeline.local_queue_worker.upload_r2_object", side_effect=fake_upload),
                patch("pipeline.local_queue_worker.verify_remote_manifest"),
            ):
                with self.assertRaisesRegex(RuntimeError, "catalog.json"):
                    process_message(
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

            # No index was rewritten -- and now nothing was written at all,
            # because the abort happens before the first body is overwritten.
            self.assertNotIn("catalog.json", uploaded)
            self.assertNotIn("seasons/2026.json", uploaded)
            self.assertEqual(uploaded, {})

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
