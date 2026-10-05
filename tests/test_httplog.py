from __future__ import annotations

import pytest
import requests

from f1data.httplog import HttpRecorder


class _Adapter(requests.adapters.BaseAdapter):
    """Answers by path so no request leaves the machine."""

    def send(self, request, **kwargs):
        if request.path_url.startswith("/unreachable"):
            raise requests.ConnectionError("no route")
        response = requests.Response()
        response.status_code = 403 if request.path_url.startswith("/static") else 200
        response.headers["server"] = "cloudflare"
        response._content = b"<html>Access   denied</html>" if response.status_code == 403 else b"{}"
        response.request = request
        response.url = request.url
        return response

    def close(self):
        pass


def _session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", _Adapter())
    return session


def test_records_status_host_and_path_and_keeps_evidence_for_a_refusal():
    with HttpRecorder() as recorder:
        _session().get("https://livetiming.formula1.com/static/2026/x/CarData.z.jsonStream?rnd=1")
        _session().get("https://api.jolpi.ca/ergast/f1/2026/8/results.json")

    refused, answered = recorder.records
    assert (refused.host, refused.path, refused.status) == (
        "livetiming.formula1.com",
        "/static/2026/x/CarData.z.jsonStream",
        403,
    )
    assert refused.headers == {"server": "cloudflare"}
    assert refused.body_excerpt == "<html>Access denied</html>"
    assert answered.status == 200 and answered.headers is None and answered.body_excerpt is None
    assert recorder.failures == [refused]
    assert recorder.summary() == {
        "api.jolpi.ca": {"200": 1},
        "livetiming.formula1.com": {"403": 1},
    }


def test_records_a_request_that_never_got_an_answer_and_still_raises():
    with HttpRecorder() as recorder, pytest.raises(requests.ConnectionError):
        _session().get("https://livetiming.formula1.com/unreachable")

    (record,) = recorder.records
    assert record.status is None
    assert record.error == "ConnectionError: no route"
    assert recorder.summary() == {"livetiming.formula1.com": {"error": 1}}


def test_stops_recording_on_exit():
    original = requests.Session.send
    with HttpRecorder() as recorder:
        assert requests.Session.send is not original
    assert requests.Session.send is original

    _session().get("https://api.jolpi.ca/ergast/f1/2026/8/results.json")
    assert recorder.records == []


def test_failure_kinds_collapses_a_session_refused_feed_by_feed():
    with HttpRecorder() as recorder:
        for feed in ("SessionInfo", "TimingData", "CarData.z"):
            _session().get(f"https://livetiming.formula1.com/static/2026/x/{feed}.jsonStream")
        _session().get("https://api.jolpi.ca/ergast/f1/2026/8/results.json")

    assert recorder.failure_kinds() == [
        {
            "method": "GET",
            "host": "livetiming.formula1.com",
            "status": 403,
            "headers": {"server": "cloudflare"},
            "body_excerpt": "<html>Access denied</html>",
            "count": 3,
            "example_path": "/static/2026/x/SessionInfo.jsonStream",
        }
    ]
