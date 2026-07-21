from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from pipeline.artifacts import build_incremental_artifacts, build_static_artifacts


def session_dataset(session_id: str, round_number: int, meeting_id: str, label: str) -> dict:
    return {
        "seasons": [{"year": 2026, "meeting_count": 2, "ingested_meeting_count": 2, "is_sample": False}],
        "meetings": [
            {
                "meeting_id": meeting_id,
                "year": 2026,
                "round": round_number,
                "name": label,
                "circuit": {"circuit_id": meeting_id, "name": label, "country": "Test"},
                "country": "Test",
                "sessions_available": ["Q"],
                "is_ingested": True,
                "is_sample": False,
            }
        ],
        "sessions": [
            {
                "session_id": session_id,
                "year": 2026,
                "round": round_number,
                "meeting_id": meeting_id,
                "name": "Qualifying",
                "type": "Q",
                "status": "available",
                "is_sample": False,
            }
        ],
        "session_data": {
            session_id: {
                "summary": {
                    "session_id": session_id,
                    "session": "Qualifying",
                    "meeting": label,
                    "year": 2026,
                    "round": round_number,
                },
                "drivers": [],
                "laps": [],
                "results": [],
                "stints": [],
                "pit_stops": [],
                "weather": [],
                "race_control": [],
                "telemetry": [],
            }
        },
    }


class ArtifactBuildTests(unittest.TestCase):
    def create_data(self, root: Path) -> tuple[Path, Path]:
        data_dir = root / "data"
        first = data_dir / "processed" / "sessions" / "2026-01-q" / "dataset.json"
        second = data_dir / "processed" / "sessions" / "2026-02-q" / "dataset.json"
        for path, payload in [
            (first, session_dataset("2026-01-q", 1, "meeting-1", "First")),
            (second, session_dataset("2026-02-q", 2, "meeting-2", "Second")),
        ]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        return data_dir, first

    def test_incremental_build_does_not_rewrite_unrelated_session(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_dir, first_dataset = self.create_data(root)
            output_dir = root / "output"
            build_static_artifacts(data_dir, output_dir, generated_at="2026-07-21T00:00:00Z")
            unrelated = output_dir / "sessions" / "2026-02-q" / "manifest.json"
            before_bytes = unrelated.read_bytes()
            before_mtime = unrelated.stat().st_mtime_ns

            payload = json.loads(first_dataset.read_text(encoding="utf-8"))
            payload["session_data"]["2026-01-q"]["summary"]["meeting"] = "First refreshed"
            first_dataset.write_text(json.dumps(payload), encoding="utf-8")
            build_incremental_artifacts(
                {"2026-01-q"}, data_dir, output_dir, generated_at="2026-07-21T01:00:00Z"
            )

            self.assertEqual(unrelated.read_bytes(), before_bytes)
            self.assertEqual(unrelated.stat().st_mtime_ns, before_mtime)
            refreshed = json.loads((output_dir / "sessions" / "2026-01-q" / "summary.json").read_text())
            self.assertEqual(refreshed["meeting"], "First refreshed")

    def test_full_build_is_deterministic_with_fixed_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_dir, _ = self.create_data(root)
            first_output = root / "first"
            second_output = root / "second"
            generated_at = "2026-07-21T00:00:00Z"
            build_static_artifacts(data_dir, first_output, generated_at=generated_at)
            build_static_artifacts(data_dir, second_output, generated_at=generated_at)

            first_files = {path.relative_to(first_output): path.read_bytes() for path in first_output.rglob("*.json")}
            second_files = {path.relative_to(second_output): path.read_bytes() for path in second_output.rglob("*.json")}
            self.assertEqual(first_files, second_files)

    def test_local_incremental_publication_adds_a_session_without_rebuilding_history(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_dir, first_dataset = self.create_data(root)
            second_dataset = data_dir / "processed" / "sessions" / "2026-02-q" / "dataset.json"
            second_payload = second_dataset.read_text(encoding="utf-8")
            second_dataset.unlink()
            output_dir = root / "output"
            build_static_artifacts(data_dir, output_dir, generated_at="2026-07-21T00:00:00Z")
            historical_manifest = output_dir / "sessions" / "2026-01-q" / "manifest.json"
            historical_bytes = historical_manifest.read_bytes()

            first_dataset.unlink()
            second_dataset.write_text(second_payload, encoding="utf-8")
            result = build_incremental_artifacts(
                {"2026-02-q"}, data_dir, output_dir, generated_at="2026-07-21T01:00:00Z"
            )
            catalog = json.loads((output_dir / "catalog.json").read_text(encoding="utf-8"))
            season = json.loads((output_dir / "seasons" / "2026.json").read_text(encoding="utf-8"))

            self.assertTrue(result["incremental"])
            self.assertEqual(
                {session["session_id"] for session in catalog["sessions"]},
                {"2026-01-q", "2026-02-q"},
            )
            self.assertEqual(
                {session["session_id"] for session in season["sessions"]},
                {"2026-01-q", "2026-02-q"},
            )
            self.assertTrue((output_dir / "sessions" / "2026-02-q" / "manifest.json").is_file())
            self.assertEqual(historical_manifest.read_bytes(), historical_bytes)

    def test_incremental_build_does_not_advertise_unselected_processed_sessions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_dir, _ = self.create_data(root)
            second_dataset = data_dir / "processed" / "sessions" / "2026-02-q" / "dataset.json"
            second_payload = second_dataset.read_text(encoding="utf-8")
            second_dataset.unlink()
            output_dir = root / "output"
            build_static_artifacts(data_dir, output_dir, generated_at="2026-07-21T00:00:00Z")

            second_dataset.write_text(second_payload, encoding="utf-8")
            third_dataset = data_dir / "processed" / "sessions" / "2026-03-q" / "dataset.json"
            third_dataset.parent.mkdir(parents=True, exist_ok=True)
            third_dataset.write_text(
                json.dumps(session_dataset("2026-03-q", 3, "meeting-3", "Third")),
                encoding="utf-8",
            )
            build_incremental_artifacts(
                {"2026-02-q"}, data_dir, output_dir, generated_at="2026-07-21T01:00:00Z"
            )

            catalog = json.loads((output_dir / "catalog.json").read_text(encoding="utf-8"))
            season = json.loads((output_dir / "seasons" / "2026.json").read_text(encoding="utf-8"))
            expected = {"2026-01-q", "2026-02-q"}
            self.assertEqual({row["session_id"] for row in catalog["sessions"]}, expected)
            self.assertEqual({row["session_id"] for row in season["sessions"]}, expected)
            self.assertFalse((output_dir / "sessions" / "2026-03-q").exists())


if __name__ == "__main__":
    unittest.main()
