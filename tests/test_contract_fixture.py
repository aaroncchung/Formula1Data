"""The contract between the publisher and whatever reads what it publishes.

``tests/fixtures/published-v1.json`` is a small bucket exactly as the publisher
writes one: an index, a pointer and a generation. This test fails when the
publisher stops producing it byte for byte; the frontend's reader is tested
against the same file (``frontend/tests/published-data.test.mjs``). A change to
a published shape therefore has to be made on both sides, in one commit.

To regenerate after an intended change:

    F1DATA_WRITE_FIXTURES=1 python -m pytest tests/test_contract_fixture.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from f1data import layout
from f1data.archive import dump_json
from f1data.publish import Inputs, publish_index, publish_session
from f1data.store import MemoryStore
from tests.test_publish import AUSTRIA, NOW, schedule_2026, snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "published-v1.json"

# In the artifact format of today, which step 2 of the rewrite keeps.
FILES = {
    "summary.json": {
        "session_id": "2026-08-r",
        "meeting": "Austrian Grand Prix",
        "session": "Race",
        "year": 2026,
        "round": 8,
        "circuit": "Spielberg",
        "country": "Austria",
        "driver_count": 2,
        "lap_count": 142,
        "weather_summary": "air 21.0-24.5C, track 38.0-44.1C, dry",
        "is_sample": False,
    },
    "drivers.json": [
        {
            "driver_id": "rus",
            "code": "RUS",
            "full_name": "George Russell",
            "number": 63,
            "team": {"team_id": "mercedes", "name": "Mercedes", "color": "#27F4D2"},
            "country": "GBR",
        },
        {
            "driver_id": "ver",
            "code": "VER",
            "full_name": "Max Verstappen",
            "number": 3,
            "team": {"team_id": "red-bull-racing", "name": "Red Bull Racing", "color": "#3671C6"},
            "country": "NED",
        },
    ],
    "results.json": [
        {
            "session_id": "2026-08-r",
            "position": 1,
            "driver_code": "RUS",
            "classified_position": "1",
            "status": "Finished",
            "points": 25.0,
            "grid": 1,
            "gap": "0 days 01:26:38.802000",
            "laps": 71,
        },
        {
            "session_id": "2026-08-r",
            "position": 2,
            "driver_code": "VER",
            "classified_position": "2",
            "status": "Finished",
            "points": 18.0,
            "grid": 5,
            "gap": "0 days 00:00:04.312000",
            "laps": 71,
        },
    ],
}


# What a build took from the calendar, as the builder records it in the pointer.
CALENDAR_ENTRY = {
    "calendar": {
        "year": 2026,
        "round": 8,
        "meeting_name": "Austrian Grand Prix",
        "session_name": "Race",
        "row": "sha256:" + "d" * 64,
    }
}


def published_bucket() -> dict[str, str]:
    store = MemoryStore()
    inputs = Inputs(snapshot(), "sha256:" + "c" * 64, also=CALENDAR_ENTRY)
    files = {path: dump_json(payload) for path, payload in FILES.items()}
    outcome = publish_session(store, AUSTRIA, lambda key, **_: inputs, lambda _: (files, None), now=lambda: NOW)
    assert outcome.action == "published"
    assert publish_index(store, lambda year, **_: schedule_2026()) == "published"
    return {item.key: store.get(item.key).data.decode("utf-8") for item in store.list("")}


def test_the_committed_fixture_is_exactly_what_the_publisher_writes(monkeypatch):
    # The fixture pins the shapes, not how many times an analysis has been
    # fixed. Held at 1 so that a pipeline version bump leaves it alone.
    monkeypatch.setattr(layout, "PIPELINE_VERSION", 1)
    expected = json.dumps(published_bucket(), indent=2, sort_keys=True) + "\n"
    if os.environ.get("F1DATA_WRITE_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        with FIXTURE.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(expected)

    assert FIXTURE.read_text(encoding="utf-8") == expected
