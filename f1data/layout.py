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
FORMAT_VERSION = 1

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
PIPELINE_VERSION = 3

ARCHIVE_PREFIX = "archive/"
SNAPSHOT_MARKER = "snapshot.json"
MANIFEST_NAME = "manifest.json"

_GENERATION_ID = re.compile(r"^[a-f0-9]{64}$")
_SNAPSHOT_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")


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
