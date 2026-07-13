from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from pipeline.schedule_ingestion import get_status, post_json, request_headers, select_candidates


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


if __name__ == "__main__":
    unittest.main()
