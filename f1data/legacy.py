"""Bridge to the pre-rewrite normaliser and artifact writer.

Step 2 of the rewrite publishes one session end to end on the real
infrastructure with the artifact contents still in the old format
(docs/architecture-review-findings.md, section 6). This module is how the new
build reaches the old code, and it is the only place that does. It goes when
step 3 lands the new format.

The old code is imported under two roots, ``app.*`` and ``backend.app.*``
(AR-10); both need to be on the path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from f1data.archive import dump_json
from f1data.identity import SessionIdentity

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# The old writer puts its own manifest beside the artifacts. The publisher
# writes the generation's manifest, so the old one is left out.
_LEGACY_MANIFEST = "manifest.json"


def build_legacy_artifacts(
    session: Any, identity: SessionIdentity, round_number: int, generated_at: str, scratch: Path
) -> dict[str, bytes]:
    """Normalise a loaded FastF1 session and return its artifacts by relative path."""
    for path in (_REPOSITORY_ROOT, _REPOSITORY_ROOT / "backend"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from app.ingestion.normalizer import normalize_fastf1_session
    from pipeline.artifacts import write_session_artifacts

    dataset = normalize_fastf1_session(identity.year, round_number, identity.session_type, session)
    session_id, bundle = next(iter(dataset["session_data"].items()))
    write_session_artifacts(
        output_dir=scratch,
        session_id=session_id,
        bundle=bundle,
        # The old telemetry index embeds this. A fixed value keeps two builds
        # of the same inputs identical.
        generated_at=generated_at,
        source_files=[],
    )

    session_dir = scratch / "sessions" / session_id
    files: dict[str, bytes] = {}
    for path in sorted(session_dir.rglob("*.json")):
        relative = path.relative_to(session_dir).as_posix()
        if relative == _LEGACY_MANIFEST:
            continue
        # Re-serialised: the old writer indents, and in text mode its line
        # endings follow the platform, which would change the generation's
        # name between Windows and Linux.
        files[relative] = dump_json(json.loads(path.read_bytes()))
    return files
