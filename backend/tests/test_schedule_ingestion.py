from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from pipeline.schedule_ingestion import (
    get_status,
    main,
    post_json,
    request_headers,
    select_candidates,
)


class ScheduleIngestionTests(unittest.TestCase):
    def test_uses_project_user_agent(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                request_headers()["user-agent"], "Formula1DataIngestion/1.0"
            )

    def test_prefers_access_credentials_over_bearer_token(self):
        with patch.dict(
            "os.environ",
            {
                "INGESTION_API_TOKEN": "token",
                "CF_ACCESS_CLIENT_ID": "client-id",
                "CF_ACCESS_CLIENT_SECRET": "client-secret",
            },
            clear=True,
        ):
            headers = request_headers()
        self.assertNotIn("authorization", headers)
        self.assertEqual(headers["CF-Access-Client-Id"], "client-id")

    def test_public_status_omits_access_headers_and_protected_write_retains_them(self):
        response = unittest.mock.MagicMock()
        response.status = 200
        response.url = "https://worker.example/api/session-status"
        response.read.return_value = b'{"status":"missing"}'
        response.__enter__.return_value = response
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "CF-Access-Client-Id": "client-id",
            "CF-Access-Client-Secret": "client-secret",
        }
        with patch("pipeline.schedule_ingestion.urllib.request.urlopen", return_value=response) as open_url:
            get_status(
                "https://worker.example",
                {"year": 2026, "round": 9, "session": "R"},
                headers,
            )
            public_headers = dict(open_url.call_args.args[0].header_items())
            self.assertNotIn("Cf-access-client-id", public_headers)
            self.assertNotIn("Cf-access-client-secret", public_headers)

        write_response = unittest.mock.MagicMock()
        write_response.__enter__.return_value = write_response
        write_response.read.return_value = b'{"action":"queued"}'
        with patch(
            "pipeline.schedule_ingestion.urllib.request.urlopen", return_value=write_response
        ) as open_url:
            post_json("https://worker.example/api/ingestion/session", {"year": 2026}, headers)
            protected_headers = dict(open_url.call_args.args[0].header_items())
            self.assertEqual(protected_headers["Cf-access-client-id"], "client-id")
            self.assertEqual(protected_headers["Cf-access-client-secret"], "client-secret")

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


    def test_meetings_without_a_usable_start_date_are_skipped(self):
        catalog = {
            "meetings": [
                {
                    "meeting_id": "2026-08-null",
                    "year": 2026,
                    "round": 8,
                    "start_date": None,
                    "sessions_available": ["R"],
                },
                {
                    "meeting_id": "2026-09-british-grand-prix",
                    "year": 2026,
                    "round": 9,
                    "start_date": "2026-07-05T00:00:00",
                    "sessions_available": ["R"],
                },
                {
                    "meeting_id": "2026-10-missing-key",
                    "year": 2026,
                    "round": 10,
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

        self.assertEqual([candidate["round"] for candidate in candidates], [9])

    def test_a_failing_candidate_does_not_starve_the_later_rounds(self):
        catalog = {
            "meetings": [
                {
                    "meeting_id": f"2026-{round_number:02d}-x",
                    "year": 2026,
                    "round": round_number,
                    "start_date": "2026-07-05T00:00:00",
                    "sessions_available": ["R"],
                }
                for round_number in (1, 2, 3)
            ]
        }
        checked: list[int] = []
        posted: list[int] = []

        def fake_status(_worker_url, candidate, _headers):
            checked.append(candidate["round"])
            if candidate["round"] == 1:
                raise RuntimeError("Ingestion API returned a non-JSON response")
            return {"status": "missing"}

        def fake_post(_url, payload, _headers):
            if payload["round"] == 2:
                raise RuntimeError("HTTP Error 500")
            posted.append(payload["round"])
            return {"action": "queued"}

        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog_path = Path(temporary_directory) / "catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

            with (
                patch("pipeline.schedule_ingestion.get_status", side_effect=fake_status),
                patch("pipeline.schedule_ingestion.post_json", side_effect=fake_post),
            ):
                with self.assertRaises(SystemExit) as raised:
                    main(
                        [
                            "--catalog",
                            str(catalog_path),
                            "--worker-url",
                            "https://worker.example",
                            "--through-date",
                            "2026-07-06",
                            "--lookback-days",
                            "4",
                            "--races-only",
                        ]
                    )

        # Every candidate was attempted, a later round was still queued after
        # both a failed status check and a failed POST, and the run reports
        # the failures rather than exiting cleanly.
        self.assertEqual(checked, [1, 2, 3])
        self.assertEqual(posted, [3])
        self.assertIn("2 session(s) could not be queued", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
