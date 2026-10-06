"""The contract between the publisher and whatever reads what it publishes.

``tests/fixtures/published-v2.json`` is a small bucket exactly as the publisher
writes one in format 2: an index, a pointer and a generation, whose files
include a nested path (``analysis/``) and a driver's telemetry. This test fails
when the publisher stops producing it byte for byte, and when anything in it
stops matching its model in ``f1data/models.py``. The Worker is tested against
the same file (``worker/tests/data-worker.test.mjs``). A change to a published
shape therefore has to be made on both sides, in one commit.

``published-v1.json`` beside it is the same bucket in the format before. It is
no longer produced by anything here, and stays until the frontend's reader,
whose tests still read it, has moved to format 2.

To regenerate after an intended change:

    F1DATA_WRITE_FIXTURES=1 python -m pytest tests/test_contract_fixture.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from f1data import layout
from f1data.archive import dump_json
from f1data.models import (
    Driver,
    Drivers,
    DriverTelemetry,
    IdealLapRow,
    IdealLaps,
    Result,
    Results,
    SessionSummary,
    Team,
    TelemetryDriverEntry,
    TelemetryIndex,
    TelemetryLap,
    TelemetryLapEntry,
    artifact_json,
)
from f1data.publish import Inputs, publish_index, publish_session
from f1data.schema import validate_published
from f1data.store import MemoryStore
from tests.test_publish import AUSTRIA, NOW, schedule_2026, snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "published-v2.json"

FILES = {
    "summary.json": SessionSummary(
        session_key=AUSTRIA,
        year=2026,
        meeting="Austrian Grand Prix",
        session="Race",
        session_type="R",
        circuit="Spielberg",
        country="Austria",
        driver_count=2,
        lap_count=142,
        weather_summary="air 33.4-35.1C, track 42.6-53.3C, dry",
        clock_zero_utc="2026-06-28T12:06:12.076Z",
        is_sample=False,
    ),
    "drivers.json": Drivers(
        [
            Driver(
                driver_id="rus",
                code="RUS",
                full_name="George Russell",
                number=63,
                team=Team(team_id="mercedes", name="Mercedes", color="#00D7B6"),
                country=None,
            ),
            Driver(
                driver_id="ver",
                code="VER",
                full_name="Max Verstappen",
                number=3,
                team=Team(team_id="red-bull", name="Red Bull", color="#4781D7"),
                country=None,
            ),
        ]
    ),
    "results.json": Results(
        [
            Result(
                position=1, driver_code="RUS", classified_position="1", status="Finished", points=25,
                grid=1, time_ms=5_197_979, gap_ms=None, laps=71, provisional=False,
            ),
            Result(
                position=2, driver_code="VER", classified_position="2", status="Finished", points=18,
                grid=5, time_ms=None, gap_ms=1_611, laps=71, provisional=False,
            ),
        ]
    ),
    "analysis/ideal-laps.json": IdealLaps(
        rows=[
            IdealLapRow(
                driver_code="RUS", best_sector_1_ms=16_982, best_sector_2_ms=30_741, best_sector_3_ms=22_301,
                ideal_lap_ms=70_024, best_lap_ms=70_238, delta_to_ideal_ms=214,
            ),
            IdealLapRow(
                driver_code="VER", best_sector_1_ms=17_010, best_sector_2_ms=30_702, best_sector_3_ms=22_365,
                ideal_lap_ms=70_077, best_lap_ms=70_302, delta_to_ideal_ms=225,
            ),
        ]
    ),
    "telemetry/index.json": TelemetryIndex(
        max_samples_per_lap=300,
        channels=["time_ms", "distance_m", "speed_kph", "throttle_pct", "brake", "rpm", "gear", "x", "y"],
        drivers=[
            TelemetryDriverEntry(
                driver_code="RUS",
                path="telemetry/RUS.json",
                laps=[TelemetryLapEntry(lap_number=2, sample_count=4, raw_sample_count=564, has_position=True)],
            )
        ],
    ),
    "telemetry/RUS.json": DriverTelemetry(
        driver_code="RUS",
        laps=[
            TelemetryLap(
                lap_number=2,
                start_ms=3_502_948,
                time_ms=[0, 267, 507, 72_037],
                distance_m=[0.0, 22.2, 41.9, 4183.6],
                speed_kph=[299.0, 299.0, 296.0, 303.0],
                throttle_pct=[100, 100, 100, 100],
                brake=[False, False, False, False],
                rpm=[11_521, 11_521, 11_281, 10_405],
                gear=[7, 7, 7, 8],
                drs=None,
                x=[-424.0, -602.7, -754.3, -387.5],
                y=[-1620.3, -1668.5, -1709.4, -1610.6],
            )
        ],
    ),
}


def published_bucket() -> dict[str, str]:
    store = MemoryStore()
    inputs = Inputs(snapshot(), "sha256:" + "c" * 64)
    files = {path: dump_json(artifact_json(artifact)) for path, artifact in FILES.items()}
    outcome = publish_session(store, AUSTRIA, lambda key, **_: inputs, lambda _: (files, None), now=lambda: NOW)
    assert outcome.action == "published"
    assert publish_index(store, lambda year, **_: schedule_2026()) == "published"
    return {item.key: store.get(item.key).data.decode("utf-8") for item in store.list("")}


def test_the_committed_fixture_is_exactly_what_the_publisher_writes(monkeypatch):
    # The fixture pins the shapes, not how many times an analysis has been
    # fixed. Held at 1 so that a pipeline version bump leaves it alone.
    monkeypatch.setattr(layout, "PIPELINE_VERSION", 1)
    assert layout.FORMAT_VERSION == 2, "a new format needs a fixture of its own, beside this one"
    expected = json.dumps(published_bucket(), indent=2, sort_keys=True) + "\n"
    if os.environ.get("F1DATA_WRITE_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        with FIXTURE.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(expected)

    assert FIXTURE.read_text(encoding="utf-8") == expected


def test_everything_in_the_fixture_is_what_its_model_says(monkeypatch):
    """The pointer, the index and the manifest are written by the publisher
    from dictionaries, not from models. This is what ties them to the schema."""
    monkeypatch.setattr(layout, "PIPELINE_VERSION", 1)
    bucket = published_bucket()
    prefix = layout.format_prefix()

    assert {key.split("/")[0] for key in bucket} == {prefix.rstrip("/")}
    for key, text in bucket.items():
        validate_published(key[len(prefix):], json.loads(text))
    nested = [key for key in bucket if "/analysis/" in key or "/telemetry/" in key]
    assert len(nested) == 3
    manifest = json.loads(next(text for key, text in bucket.items() if key.endswith("/manifest.json")))
    assert manifest["format_version"] == layout.FORMAT_VERSION and "schema_version" not in manifest
