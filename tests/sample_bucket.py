"""A small made-up race, published the way a real one is, for working on the site without the network.

    python -m tests.sample_bucket <directory>
    python -m tests.sample_bucket <directory> --serve [--port 8788]

Writes the published layout under ``<directory>``: the index of a season of
two meetings, the season's standings, a pointer and a generation of the
stand-in race the tests are built on (tests/race.py: three drivers, twelve
laps of a circular track), with every file a real race has. One meeting is
left unpublished, as a weekend that has not been run is. Nothing in it is
F1's data, so nothing of F1's is committed for the sake of a sample.

It is made by the publisher's own code, so it is what the Worker serves in
every respect but size. ``--serve`` then serves it as the Worker does, at
``http://localhost:<port>/data``, with the header a page on another port
needs. Point the site at it with::

    NEXT_PUBLIC_PUBLISHED_DATA_BASE_URL=http://localhost:8788/data

in ``frontend/.env.local``. The sample race opens at ``/session?key=9001``.
"""

from __future__ import annotations

import argparse
import http.server
import sys
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from f1data import layout
from f1data.archive import Snapshot
from f1data.artifacts import build_artifacts
from f1data.coverage import apply_classification, measure_coverage
from f1data.publish import Inputs, publish_index, publish_session
from f1data.schedule import ScheduledSession
from f1data.standings import publish_standings
from f1data.store import DirectoryStore, ObjectStore
from tests.race import DRIVERS, classification, extras, make_race
from tests.race import IDENTITY as STAND_IN

# The stand-in race as the first round of a season of two.
IDENTITY = replace(STAND_IN, round_at_fetch=1)

PUBLISHED_AT = datetime(2026, 6, 28, 20, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = "20260628T180000Z-5a3b1e00"
# Served under this path, as the Worker serves the bucket under /data.
SERVED_UNDER = "/data/"


def season() -> list[ScheduledSession]:
    """The calendar the index is made from: the sample race, and a weekend still to come."""

    def entry(round_number: int, name: str, location: str, start: str) -> ScheduledSession:
        return ScheduledSession(
            year=IDENTITY.year,
            round=round_number,
            meeting_name=name,
            meeting_official_name=f"FORMULA 1 {name.upper()} {IDENTITY.year}",
            country=IDENTITY.country,
            location=location,
            meeting_date=start[:10],
            meeting_format="conventional",
            session_type="R",
            session_name="Race",
            start_time_utc=start,
        )

    return [
        entry(IDENTITY.round_at_fetch or 1, IDENTITY.meeting_name, IDENTITY.location or "", IDENTITY.start_time_utc),
        entry((IDENTITY.round_at_fetch or 1) + 1, "Coast Grand Prix", "Kuestenstadt", "2026-07-12T13:00:00Z"),
    ]


def standings() -> dict:
    """The season's tables after the sample race, as the job stores them."""
    points = {"AAA": 25, "BBB": 18, "CCC": 0}
    by_code = {driver["code"]: (number, driver) for number, driver in DRIVERS.items()}
    teams: dict[str, int] = {}
    for code, scored in points.items():
        team = by_code[code][1]["team"]
        teams[team] = teams.get(team, 0) + scored
    return {
        "schema_version": 1,
        "format_version": 2,
        "year": IDENTITY.year,
        "rounds": {"drivers": IDENTITY.round_at_fetch, "constructors": IDENTITY.round_at_fetch},
        "drivers": [
            {
                "position": position,
                "points": points[code],
                "wins": 1 if position == 1 else 0,
                "driver_code": code,
                "driver_number": int(by_code[code][0]),
                "given_name": by_code[code][1]["name"].split()[0],
                "family_name": by_code[code][1]["name"].split()[-1],
                "constructors": [by_code[code][1]["team"]],
            }
            for position, code in enumerate(points, start=1)
        ],
        "constructors": [
            {
                "position": position,
                "points": scored,
                "wins": 1 if position == 1 else 0,
                "constructor_id": name.lower().replace(" ", "_"),
                "name": name,
            }
            for position, (name, scored) in enumerate(sorted(teams.items(), key=lambda item: -item[1]), start=1)
        ],
    }


def write_sample(store: ObjectStore) -> list[str]:
    """Publish the sample into ``store`` and return what happened, a line for each thing published."""
    session, found, result = make_race(), extras(), classification()
    measurement = apply_classification(measure_coverage(session, "R", found), result.laps_by_number)
    files = build_artifacts(session, IDENTITY, result, found, measurement)
    snapshot = Snapshot(
        snapshot_id=SNAPSHOT_ID, identity=IDENTITY, fetched_at="2026-06-28T18:00:00Z", coverage=measurement
    )
    calendar = {
        "calendar": {
            "year": IDENTITY.year,
            "round": IDENTITY.round_at_fetch,
            "meeting_name": IDENTITY.meeting_name,
            "session_name": IDENTITY.session_name,
            "row": "sha256:" + "5" * 64,
        }
    }
    inputs = Inputs(snapshot, result.fingerprint, also=calendar)
    outcome = publish_session(
        store, IDENTITY.session_key, lambda key, **_: inputs, lambda _: (files, None), now=lambda: PUBLISHED_AT
    )
    return [
        f"session {IDENTITY.session_key}: {outcome.action}, {len(files)} files",
        f"index: {publish_index(store, lambda year, **_: season())}",
        f"standings {IDENTITY.year}: {publish_standings(store, IDENTITY.year, lambda year: standings())}",
    ]


class _AsTheWorkerServes(http.server.SimpleHTTPRequestHandler):
    """Files of the directory under ``/data/``, readable from a page on any origin."""

    def translate_path(self, path: str) -> str:
        # What is published, and nothing else the directory may hold: the
        # Worker never serves the archive (worker/src/published-data.mjs).
        nothing = str(Path(self.directory) / "not-served")
        key = path[len(SERVED_UNDER) :] if path.startswith(SERVED_UNDER) else ""
        if not key.startswith(f"v{layout.FORMAT_VERSION}/"):
            return nothing
        # And where the address leads once it is decoded, not what it starts
        # with: `v2/%2e%2e/archive/...` starts with `v2/`.
        published = (Path(self.directory) / f"v{layout.FORMAT_VERSION}").resolve()
        found = Path(super().translate_path("/" + key)).resolve()
        return str(found) if published in found.parents else nothing

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def list_directory(self, path: str):  # noqa: ANN201
        self.send_error(404, "Not found")
        return None


def serve(directory: Path, port: int) -> None:
    handler = partial(_AsTheWorkerServes, directory=str(directory))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Serving {directory} at http://localhost:{port}{SERVED_UNDER.rstrip('/')}  (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("directory", type=Path, help="Where to write the sample. Made if it is not there.")
    parser.add_argument("--serve", action="store_true", help="Then serve it as the Worker serves the bucket.")
    parser.add_argument("--port", type=int, default=8788)
    options = parser.parse_args(arguments)
    for line in write_sample(DirectoryStore(options.directory)):
        print(line)
    if options.serve:
        serve(options.directory, options.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
