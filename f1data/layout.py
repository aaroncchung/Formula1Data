"""Where everything lives in the bucket, and the two version numbers.

    archive/sessions/<session_key>/<snapshot_id>/   source archive, never served
    v<F>/pointers/<session_key>.json                one per published session
    v<F>/generations/<session_key>/<generation>/    immutable artifacts
    v<F>/index.json                                 derived from the pointers and the schedule
    v<F>/standings/<year>.json

Pointers sit under one prefix so that "which sessions are published" is one
list call (docs/architecture-review-findings.md, section 6, rule 3). The format
version is part of the path so that a frontend built for one format never reads
another (rule 7).
"""

from __future__ import annotations

import re

# The artifact format: file names, shapes and units. A change here is published
# under a new prefix before the frontend that reads it is deployed.
#
#   2  one model per artifact (f1data/models.py): columnar telemetry bundled
#      per driver, whole milliseconds, null for a missing value, floats
#      rounded as they are written, nothing taken from the calendar
FORMAT_VERSION = 2

# Everything that changes what a build produces without changing the format: an
# analysis fix, a coverage bar. A pointer written by an older pipeline version
# is rebuilt; one written by a newer version is never replaced (rule 2).
#
# A coverage bar counts: a pointer records whether its session met the bars,
# so a session judged complete under an old bar has to be judged again.
# tests/test_layout.py fails when a bar changes and this number does not.
#
#   2  the analysis method fixes of AR-08: pit loss, pace change across a
#      stop, track dominance, tyre degradation fits, team-mate comparison
#   3  coverage: no tolerance on timing laps, the tyre bar without tyre age,
#      bars for the pit-stop feed and the corner positions
#   4  a driver that today's classification leaves out carries no result
#      from the archive into a build; a corner count that is absent no
#      longer passes; the pointer records the calendar entry it was built
#      under, and a session is rebuilt when that changes
#   5  a build is made from the calendar row that was gathered, and reads
#      nothing over the network: the result and the first-lap times FastF1
#      used to fetch from Jolpica while loading are fetched beforehand and
#      are in the fingerprint; a record that disagrees with its feeds is
#      corrected before anything is decided from it
#   6  format 2: analyses read full-resolution telemetry, lap times are
#      rounded and not cut off, corners are the circuit's own where archived,
#      and nothing in a build comes from the calendar
PIPELINE_VERSION = 6

ARCHIVE_PREFIX = "archive/"
# Notes of fetches that failed, by calendar entry. Not part of the archive:
# they order the next run's fetches and nothing else reads them.
ATTEMPTS_PREFIX = f"{ARCHIVE_PREFIX}attempts/"
SNAPSHOT_MARKER = "snapshot.json"
# Beside a snapshot whose record a build found to disagree with its feeds.
REMEASUREMENT_NAME = "remeasured.json"
MANIFEST_NAME = "manifest.json"

_GENERATION_ID = re.compile(r"^[a-f0-9]{64}$")
_SNAPSHOT_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")


def attempt_key(year: int, session_type: str, start_time_utc: str) -> str:
    """Where a failed fetch of a calendar entry is noted.

    By what the calendar says of the session, since a session that has never
    been fetched has no session key yet.
    """
    start = "".join(character for character in start_time_utc if character.isalnum())
    if not start or not session_type.isalnum():
        raise ValueError(f"Not a calendar entry: {session_type!r} at {start_time_utc!r}")
    return f"{ATTEMPTS_PREFIX}{int(year)}/{start}-{session_type.upper()}.json"


def snapshot_from_marker_key(key: str) -> tuple[int, str] | None:
    """The session key and snapshot id a marker's key places it under, or ``None``
    for a key that is not where a snapshot's marker goes."""
    prefix = f"{ARCHIVE_PREFIX}sessions/"
    parts = key[len(prefix):].split("/") if key.startswith(prefix) else []
    if len(parts) != 3 or parts[2] != SNAPSHOT_MARKER or not parts[0].isdigit() or not is_snapshot_id(parts[1]):
        return None
    return int(parts[0]), parts[1]


def format_prefix(format_version: int = FORMAT_VERSION) -> str:
    return f"v{format_version}/"


def pointers_prefix(format_version: int = FORMAT_VERSION) -> str:
    return f"{format_prefix(format_version)}pointers/"


def pointer_key(session_key: int, format_version: int = FORMAT_VERSION) -> str:
    return f"{pointers_prefix(format_version)}{int(session_key)}.json"


def session_key_from_pointer_key(key: str, format_version: int = FORMAT_VERSION) -> int | None:
    prefix = pointers_prefix(format_version)
    name = key[len(prefix):] if key.startswith(prefix) else ""
    stem = name[: -len(".json")] if name.endswith(".json") else ""
    return int(stem) if stem.isdigit() else None


def generation_prefix(session_key: int, generation: str, format_version: int = FORMAT_VERSION) -> str:
    if not is_generation_id(generation):
        raise ValueError(f"Not a generation id: {generation!r}")
    return f"{format_prefix(format_version)}generations/{int(session_key)}/{generation}/"


def index_key(format_version: int = FORMAT_VERSION) -> str:
    return f"{format_prefix(format_version)}index.json"


def standings_key(year: int, format_version: int = FORMAT_VERSION) -> str:
    return f"{format_prefix(format_version)}standings/{int(year)}.json"


def session_archive_prefix(session_key: int) -> str:
    return f"{ARCHIVE_PREFIX}sessions/{int(session_key)}/"


def snapshot_prefix(session_key: int, snapshot_id: str) -> str:
    if not is_snapshot_id(snapshot_id):
        raise ValueError(f"Not a snapshot id: {snapshot_id!r}")
    return f"{session_archive_prefix(session_key)}{snapshot_id}/"


def is_generation_id(value: object) -> bool:
    return isinstance(value, str) and bool(_GENERATION_ID.match(value))


def is_snapshot_id(value: object) -> bool:
    return isinstance(value, str) and bool(_SNAPSHOT_ID.match(value))
