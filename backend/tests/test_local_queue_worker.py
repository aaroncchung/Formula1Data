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
    prune_superseded_generation,
    publication_generation_id,
    publish_active_generation,
    publish_session_generation,
    read_active_generation,
    session_artifacts_exist,
    sync_artifacts_to_r2,
    upload_r2_object,
    validate_manifest_sections,
    verify_remote_manifest,
    verify_remote_publication,
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
                            output_dir,
                            "test-bucket",
                            session_id="2025-09-r",
                            year=2025,
                        )

    def _generation_manifest(self, session_id="2025-09-r", sections=None):
        return {
            "session_id": session_id,
            "generated_at": "2026-07-26T00:00:00+00:00",
            "sections": sections
            if sections is not None
            else [
                {
                    "kind": "summary",
                    "path": f"sessions/{session_id}/summary.json",
                    "size_bytes": 2,
                    "checksum": "sha256:" + "0" * 64,
                }
            ],
        }

    def _write_generation_tree(self, output_dir, session_id="2025-09-r", body_count=0):
        """A session tree whose manifest actually describes what is on disk."""
        session_dir = output_dir / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        summary_path = session_dir / "summary.json"
        summary_path.write_text("{}", encoding="utf-8")
        sections = [
            {
                "kind": "summary",
                "path": f"sessions/{session_id}/summary.json",
                "size_bytes": summary_path.stat().st_size,
                "checksum": checksum_file(summary_path),
            }
        ]
        if body_count:
            (session_dir / "telemetry").mkdir(parents=True, exist_ok=True)
            laps = []
            for index in range(body_count):
                lap_path = session_dir / "telemetry" / f"ver-lap-{index}.json"
                lap_path.write_text("{}", encoding="utf-8")
                relative = f"telemetry/ver-lap-{index}.json"
                laps.append({"path": relative})
                sections.append(
                    {
                        "kind": "telemetry-lap",
                        "path": f"sessions/{session_id}/{relative}",
                        "size_bytes": lap_path.stat().st_size,
                        "checksum": checksum_file(lap_path),
                    }
                )
            index_path = session_dir / "telemetry" / "index.json"
            write_json(index_path, {"laps": laps})
            sections.append(
                {
                    "kind": "telemetry-index",
                    "path": f"sessions/{session_id}/telemetry/index.json",
                    "size_bytes": index_path.stat().st_size,
                    "checksum": checksum_file(index_path),
                }
            )
        write_json(session_dir / "manifest.json", self._generation_manifest(session_id, sections))
        (output_dir / "seasons").mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "seasons" / "2025.json", {})
        write_json(output_dir / "catalog.json", {})
        return publication_generation_id(output_dir, session_id)

    def test_session_objects_are_written_under_an_immutable_generation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            generation_id = self._write_generation_tree(output_dir, body_count=2)

            with patch("pipeline.local_queue_worker.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = ""
                run.return_value.stderr = ""
                sync_artifacts_to_r2(
                    output_dir,
                    "test-bucket",
                    session_id="2025-09-r",
                    year=2025,
                    include_indexes=False,
                    generation_id=generation_id,
                )

            keys = [call.args[0][4] for call in run.call_args_list]
            base = f"test-bucket/sessions/2025-09-r/generations/{generation_id}"
            self.assertEqual(
                sorted(keys),
                sorted(
                    [
                        f"{base}/summary.json",
                        f"{base}/telemetry/ver-lap-0.json",
                        f"{base}/telemetry/ver-lap-1.json",
                        f"{base}/telemetry/index.json",
                        f"{base}/manifest.json",
                    ]
                ),
            )
            # Nothing lands at the conventional key: that is what makes the flip,
            # rather than any individual upload, the moment a session changes.
            self.assertNotIn("test-bucket/sessions/2025-09-r/summary.json", keys)
            # The manifest goes last, so a generation abandoned part-way is
            # identifiable as incomplete and cannot be pruned by manifest lookup.
            self.assertEqual(keys[-1], f"{base}/manifest.json")

    def test_the_generation_id_is_the_manifest_checksum(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            generation_id = self._write_generation_tree(output_dir)
            manifest_path = output_dir / "sessions" / "2025-09-r" / "manifest.json"
            self.assertEqual(
                f"sha256:{generation_id}",
                checksum_file(manifest_path),
            )

    def test_a_failed_body_upload_never_flips_the_pointer(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            self._write_generation_tree(output_dir, body_count=3)

            def fake_run(args, **kwargs):
                if "ver-lap-1.json" in args[4]:
                    return SimpleNamespace(returncode=1, stdout="", stderr="upload exploded")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("pipeline.local_queue_worker._REQUEST_PACER.acquire"),
                patch("pipeline.local_queue_worker._sleep_before_retry"),
                patch("pipeline.local_queue_worker.read_active_generation", return_value=None),
                patch("pipeline.local_queue_worker.publish_active_generation") as flip,
                patch("pipeline.local_queue_worker.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaises(RuntimeError):
                    publish_session_generation(
                        output_dir,
                        "test-bucket",
                        "",
                        session_id="2025-09-r",
                        year=2025,
                    )

            # The whole point: the live generation is whatever the pointer named
            # before this run, and this run never touched the pointer.
            flip.assert_not_called()

    def test_a_failed_verification_never_flips_the_pointer(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            self._write_generation_tree(output_dir)

            with (
                patch("pipeline.local_queue_worker.sync_artifacts_to_r2"),
                patch("pipeline.local_queue_worker.read_active_generation", return_value=None),
                patch(
                    "pipeline.local_queue_worker.verify_remote_publication",
                    side_effect=RuntimeError("Remote R2 artifact checksum mismatch"),
                ),
                patch("pipeline.local_queue_worker.publish_active_generation") as flip,
            ):
                with self.assertRaises(RuntimeError):
                    publish_session_generation(
                        output_dir,
                        "test-bucket",
                        "",
                        session_id="2025-09-r",
                        year=2025,
                    )

            flip.assert_not_called()

    def test_the_pointer_names_the_generation_it_replaced(self):
        previous = "a" * 64
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            generation_id = self._write_generation_tree(output_dir)
            uploaded = {}

            def fake_upload(path, bucket, key):
                uploaded[key] = json.loads(Path(path).read_text(encoding="utf-8"))

            with (
                patch("pipeline.local_queue_worker.upload_r2_object", side_effect=fake_upload),
                patch("pipeline.local_queue_worker.download_r2_object") as download,
            ):
                # The read-back compares the remote pointer to the local one, so
                # the stub has to reproduce the bytes that were just written.
                def fake_download(bucket, key, destination, **kwargs):
                    write_json(Path(destination), uploaded[key])
                    return True

                download.side_effect = fake_download
                pointer = publish_active_generation(
                    output_dir,
                    "test-bucket",
                    "",
                    "2025-09-r",
                    generation_id,
                    replaced={"generation_id": previous, "previous_generation": None},
                )

        self.assertEqual(pointer["schema_version"], 1)
        self.assertEqual(pointer["session_id"], "2025-09-r")
        self.assertEqual(
            pointer["artifact_base_path"],
            f"sessions/2025-09-r/generations/{generation_id}",
        )
        self.assertEqual(pointer["previous_generation"], previous)
        self.assertEqual(pointer["manifest"]["checksum"], f"sha256:{generation_id}")

    def test_a_pointer_that_does_not_read_back_fails_the_publication(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            generation_id = self._write_generation_tree(output_dir)

            def fake_download(bucket, key, destination, **kwargs):
                write_json(Path(destination), {"schema_version": 1, "tampered": True})
                return True

            with (
                patch("pipeline.local_queue_worker.upload_r2_object"),
                patch(
                    "pipeline.local_queue_worker.download_r2_object", side_effect=fake_download
                ),
            ):
                with self.assertRaises(RuntimeError) as raised:
                    publish_active_generation(
                        output_dir, "test-bucket", "", "2025-09-r", generation_id
                    )

        self.assertIn("active generation mismatch", str(raised.exception))

    def _publication_chain(self, contents):
        """Publish each content in turn into one fake bucket, return the trace.

        Drives the real `publish_session_generation`, so the pointer chain and
        the pruning decisions are the ones production would make. Returns, per
        step, the live generation and whether its objects survived -- which is
        the only thing that actually matters to a reader.
        """
        objects: dict[str, str] = {}
        trace = []

        def fake_upload(path, _bucket, key):
            objects[key] = Path(path).read_text(encoding="utf-8")

        def fake_download(_bucket, key, destination, **_kwargs):
            if key not in objects:
                return False
            Path(destination).write_text(objects[key], encoding="utf-8")
            return True

        def fake_delete(_bucket, key):
            objects.pop(key, None)

        for content in contents:
            with tempfile.TemporaryDirectory() as temporary_directory:
                output_dir = Path(temporary_directory)
                session_dir = output_dir / "sessions" / "2025-09-r"
                summary_path = session_dir / "summary.json"
                write_json(summary_path, {"content": content})
                write_json(
                    session_dir / "manifest.json",
                    {
                        "session_id": "2025-09-r",
                        "generated_at": "2026-07-27T00:00:00+00:00",
                        "sections": [
                            {
                                "kind": "summary",
                                "path": "sessions/2025-09-r/summary.json",
                                "size_bytes": summary_path.stat().st_size,
                                "checksum": checksum_file(summary_path),
                            }
                        ],
                    },
                )
                with (
                    patch(
                        "pipeline.local_queue_worker.upload_r2_object", side_effect=fake_upload
                    ),
                    patch(
                        "pipeline.local_queue_worker.download_r2_object",
                        side_effect=fake_download,
                    ),
                    patch(
                        "pipeline.local_queue_worker.delete_r2_object", side_effect=fake_delete
                    ),
                    patch("pipeline.local_queue_worker.verify_remote_publication"),
                ):
                    result = publish_session_generation(
                        output_dir,
                        "test-bucket",
                        "",
                        session_id="2025-09-r",
                        year=2025,
                    )
            live = result["generation_id"]
            live_base = f"sessions/2025-09-r/generations/{live}/"
            trace.append(
                {
                    "live": live,
                    "previous": result["pointer"]["previous_generation"],
                    "live_objects": sum(1 for key in objects if key.startswith(live_base)),
                    "pruned": result["pruned"],
                }
            )
        return trace, objects

    def test_republishing_unchanged_content_never_deletes_the_live_generation(self):
        """The regression: identical content republishes onto identical keys.

        A generation is named by its manifest checksum, so the third publication
        of unchanged artifacts used to find its own live generation recorded as
        the one two steps back, and delete every object in it. `active.json`
        survived, pointing at nothing -- a session live and unreadable, with the
        rollback machinery already removed. The reuse path publishes from the
        committed checkout, so this was reachable on an ordinary re-run.
        """
        trace, _ = self._publication_chain(["same", "same", "same", "same"])

        self.assertEqual(len({step["live"] for step in trace}), 1)
        for index, step in enumerate(trace):
            self.assertGreater(
                step["live_objects"], 0, f"publication {index + 1} deleted its own live generation"
            )
            self.assertNotEqual(step["previous"], step["live"])
            self.assertEqual(step["pruned"], [])

    def test_reverting_to_earlier_content_never_deletes_the_live_generation(self):
        trace, objects = self._publication_chain(["a", "b", "a"])

        self.assertEqual(trace[0]["live"], trace[2]["live"])
        self.assertGreater(trace[2]["live_objects"], 0)
        # The revert republishes generation A while A is what the outgoing
        # pointer names as its predecessor, so A is both the deletion candidate
        # and the live generation.
        self.assertEqual(trace[2]["pruned"], [])
        self.assertIn(
            f"sessions/2025-09-r/generations/{trace[2]['live']}/summary.json", objects
        )

    def test_a_normal_chain_still_prunes_the_generation_two_flips_back(self):
        trace, objects = self._publication_chain(["a", "b", "c"])

        first, second, third = (step["live"] for step in trace)
        self.assertEqual(len({first, second, third}), 3)
        # Third publication drops the first and keeps the second.
        self.assertEqual(
            trace[2]["pruned"],
            [
                f"sessions/2025-09-r/generations/{first}/summary.json",
                f"sessions/2025-09-r/generations/{first}/manifest.json",
            ],
        )
        self.assertFalse(
            any(key.startswith(f"sessions/2025-09-r/generations/{first}/") for key in objects)
        )
        self.assertTrue(
            any(key.startswith(f"sessions/2025-09-r/generations/{second}/") for key in objects)
        )

    def test_a_republish_between_two_changes_keeps_the_real_predecessor(self):
        """x, y, y again, z -- the republish must not lose x's place in the chain."""
        trace, objects = self._publication_chain(["x", "y", "y", "z"])

        first = trace[0]["live"]
        second = trace[1]["live"]
        # The republish of y displaces nothing, so x stays the predecessor and
        # survives; only the move to z retires it.
        self.assertEqual(trace[2]["previous"], first)
        self.assertEqual(trace[2]["pruned"], [])
        self.assertEqual(trace[3]["previous"], second)
        self.assertFalse(
            any(key.startswith(f"sessions/2025-09-r/generations/{first}/") for key in objects)
        )
        self.assertTrue(
            any(key.startswith(f"sessions/2025-09-r/generations/{second}/") for key in objects)
        )

    def test_pruning_removes_the_generation_two_flips_back(self):
        doomed = "b" * 64
        base = f"sessions/2025-09-r/generations/{doomed}"
        manifest = self._generation_manifest(
            sections=[
                {
                    "kind": "summary",
                    "path": "sessions/2025-09-r/summary.json",
                    "size_bytes": 2,
                    "checksum": "sha256:" + "0" * 64,
                },
                {
                    "kind": "telemetry-lap",
                    "path": "sessions/2025-09-r/telemetry/ver-lap-0.json",
                    "size_bytes": 2,
                    "checksum": "sha256:" + "0" * 64,
                },
            ]
        )

        def fake_download(bucket, key, destination, **kwargs):
            write_json(Path(destination), manifest)
            return True

        with (
            patch("pipeline.local_queue_worker.download_r2_object", side_effect=fake_download),
            patch("pipeline.local_queue_worker.delete_r2_object") as delete,
        ):
            deleted = prune_superseded_generation(
                "test-bucket",
                "",
                "2025-09-r",
                {"generation_id": "c" * 64, "previous_generation": doomed},
                live="d" * 64,
                retained="c" * 64,
            )

        self.assertEqual(
            deleted,
            [
                f"{base}/summary.json",
                f"{base}/telemetry/ver-lap-0.json",
                f"{base}/manifest.json",
            ],
        )
        # The manifest is removed last: an interrupted prune leaves a generation
        # that still has one, so a later attempt can still find the rest.
        self.assertEqual(delete.call_args_list[-1].args[1], f"{base}/manifest.json")

    def test_pruning_keeps_the_live_generation_and_the_one_before_it(self):
        """A reader that resolved the pointer just before a flip is still reading."""
        with patch("pipeline.local_queue_worker.delete_r2_object") as delete:
            # A first publication has nothing behind it at all.
            self.assertEqual(
                prune_superseded_generation(
                    "b", "", "2025-09-r", None, live="a" * 64, retained=None
                ),
                [],
            )
            # A second still has only the live generation and its predecessor.
            self.assertEqual(
                prune_superseded_generation(
                    "b",
                    "",
                    "2025-09-r",
                    {"generation_id": "a" * 64, "previous_generation": None},
                    live="b" * 64,
                    retained="a" * 64,
                ),
                [],
            )
            # And the guard refuses a candidate that is live or retained, even
            # when the chain names it -- which is what a content revert produces.
            self.assertEqual(
                prune_superseded_generation(
                    "b",
                    "",
                    "2025-09-r",
                    {"generation_id": "b" * 64, "previous_generation": "a" * 64},
                    live="a" * 64,
                    retained="b" * 64,
                ),
                [],
            )
        delete.assert_not_called()

    def test_a_prune_that_fails_does_not_fail_a_committed_publication(self):
        with (
            patch("pipeline.local_queue_worker.download_r2_object", return_value=True),
            patch(
                "pipeline.local_queue_worker.read_json",
                side_effect=RuntimeError("bucket unreachable"),
            ),
            patch("pipeline.local_queue_worker.delete_r2_object") as delete,
        ):
            deleted = prune_superseded_generation(
                "test-bucket",
                "",
                "2025-09-r",
                {"generation_id": "c" * 64, "previous_generation": "b" * 64},
                live="d" * 64,
                retained="c" * 64,
            )

        self.assertEqual(deleted, [])
        delete.assert_not_called()

    def test_an_unreadable_pointer_prunes_nothing_rather_than_guessing(self):
        with patch("pipeline.local_queue_worker.download_r2_object", return_value=False):
            self.assertIsNone(read_active_generation("test-bucket", "", "2025-09-r"))

        def fake_download(bucket, key, destination, **kwargs):
            Path(destination).write_text("not json at all", encoding="utf-8")
            return True

        with patch("pipeline.local_queue_worker.download_r2_object", side_effect=fake_download):
            self.assertIsNone(read_active_generation("test-bucket", "", "2025-09-r"))

    def test_a_pointer_naming_another_session_is_not_trusted(self):
        def fake_download(bucket, key, destination, **kwargs):
            write_json(
                Path(destination),
                {
                    "schema_version": 1,
                    "session_id": "2025-09-r",
                    "artifact_base_path": f"sessions/2025-08-r/generations/{'a' * 64}",
                },
            )
            return True

        with patch("pipeline.local_queue_worker.download_r2_object", side_effect=fake_download):
            self.assertIsNone(read_active_generation("test-bucket", "", "2025-09-r"))

    def test_remote_verification_reads_back_every_structural_artifact(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            generation_id = self._write_generation_tree(output_dir, body_count=3)
            requested = []

            def fake_download(bucket, key, destination, **kwargs):
                requested.append(key)
                relative = key.split(f"generations/{generation_id}/", 1)[1]
                source = output_dir / "sessions" / "2025-09-r" / relative
                Path(destination).write_bytes(source.read_bytes())
                return True

            with patch(
                "pipeline.local_queue_worker.download_r2_object", side_effect=fake_download
            ):
                result = verify_remote_publication(
                    output_dir, "test-bucket", "", "2025-09-r", generation_id=generation_id
                )

        self.assertTrue(result["verified"])
        self.assertEqual(result["artifact_count"], 5)
        # Summary, telemetry index and the manifest are read back; the three
        # telemetry lap bodies are not, which is what keeps a refresh from
        # doubling its R2 operations.
        self.assertEqual(result["verified_count"], 2)
        self.assertNotIn(
            f"sessions/2025-09-r/generations/{generation_id}/telemetry/ver-lap-0.json",
            requested,
        )

    def test_remote_verification_rejects_a_corrupt_artifact(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            generation_id = self._write_generation_tree(output_dir)

            def fake_download(bucket, key, destination, **kwargs):
                if key.endswith("manifest.json"):
                    Path(destination).write_bytes(
                        (output_dir / "sessions" / "2025-09-r" / "manifest.json").read_bytes()
                    )
                else:
                    Path(destination).write_text("corrupted", encoding="utf-8")
                return True

            with patch(
                "pipeline.local_queue_worker.download_r2_object", side_effect=fake_download
            ):
                with self.assertRaises(RuntimeError) as raised:
                    verify_remote_publication(
                        output_dir, "test-bucket", "", "2025-09-r", generation_id=generation_id
                    )

        self.assertIn("size mismatch", str(raised.exception))

    def test_a_manifest_listing_laps_with_no_index_is_rejected(self):
        manifest = self._generation_manifest(
            sections=[
                {
                    "kind": "summary",
                    "path": "sessions/2025-09-r/summary.json",
                    "size_bytes": 2,
                    "checksum": "sha256:" + "0" * 64,
                },
                {
                    "kind": "telemetry-lap",
                    "path": "sessions/2025-09-r/telemetry/ver-lap-0.json",
                    "size_bytes": 2,
                    "checksum": "sha256:" + "0" * 64,
                },
            ]
        )
        with self.assertRaises(RuntimeError) as raised:
            validate_manifest_sections(Path("unused"), manifest, "2025-09-r")
        self.assertIn("no index", str(raised.exception))

    def test_a_session_with_no_telemetry_at_all_still_validates(self):
        sections = validate_manifest_sections(
            Path("unused"), self._generation_manifest(), "2025-09-r"
        )
        self.assertEqual(len(sections), 1)

    def test_a_manifest_section_escaping_the_session_is_rejected(self):
        manifest = self._generation_manifest(
            sections=[
                {
                    "kind": "summary",
                    "path": "sessions/2025-09-r/../2025-08-r/summary.json",
                    "size_bytes": 2,
                    "checksum": "sha256:" + "0" * 64,
                }
            ]
        )
        with self.assertRaises(RuntimeError):
            validate_manifest_sections(Path("unused"), manifest, "2025-09-r")
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

            uploaded: dict[str, object] = {}

            def fake_download(_bucket, key, destination, **_kwargs):
                # Serve back anything this run has already written, which is how
                # the pointer read-back inside the flip sees its own bytes.
                if key in uploaded:
                    write_json(destination, uploaded[key])
                    return True
                if key.endswith("active.json"):
                    # The session has no published generation yet.
                    return False
                write_json(destination, remote_catalog if "catalog" in key else remote_season)
                return True

            def fake_upload(path, _bucket, key):
                uploaded[key] = read_json(path)

            generation_id = publication_generation_id(output_dir, session_id)

            with (
                patch.dict(os.environ, {}),
                patch(
                    "pipeline.local_queue_worker.download_r2_object", side_effect=fake_download
                ),
                patch("pipeline.local_queue_worker.upload_r2_object", side_effect=fake_upload),
                patch("pipeline.local_queue_worker.verify_remote_publication"),
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
            # The reuse path publishes a generation and flips the pointer too --
            # it is the same publication, just from the committed checkout.
            self.assertIn(
                f"sessions/{session_id}/generations/{generation_id}/manifest.json", uploaded
            )
            self.assertIn(f"sessions/{session_id}/active.json", uploaded)
            self.assertEqual(
                uploaded[f"sessions/{session_id}/active.json"]["artifact_base_path"],
                f"sessions/{session_id}/generations/{generation_id}",
            )
            self.assertNotIn(f"sessions/{session_id}/manifest.json", uploaded)
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

        Under immutable generations the abort no longer has to come before the
        first write, because there is no longer a destructive first write to get
        ahead of: the session's objects go to a generation prefix nothing points
        at. What still must not happen is a republished index.
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
                patch("pipeline.local_queue_worker.verify_remote_publication"),
                patch("pipeline.local_queue_worker.publish_active_generation") as flip,
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

            # The property that matters: no index was rewritten, so no client
            # sees a catalog holding only this session.
            self.assertNotIn("catalog.json", uploaded)
            self.assertNotIn("seasons/2026.json", uploaded)
            # Generation objects may well have been written by this point. They
            # are inert -- no pointer names them, so nothing can read them --
            # and a re-run producing the same manifest reuses the same keys.
            self.assertTrue(
                all(key.startswith(f"sessions/{session_id}/generations/") for key in uploaded),
                uploaded,
            )
            flip.assert_called_once()

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