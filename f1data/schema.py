"""The published format as one JSON Schema document.

The models in ``f1data/models.py`` are the contract; this is the form of them
a reader in another language can use. ``python -m f1data schema`` writes it to
``schema/published-v<format>.schema.json``, which is committed, and
tests/test_schema.py fails when the file and the models disagree, so a change
to a published shape cannot land without the schema changing with it.

The document is an object with one property for every kind of object that is
published, keyed by its path under the format's prefix (``v2/``), each
pointing at a named definition. A type generator given the document therefore
produces a named type for every artifact and a map from path to type.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from pydantic.json_schema import models_json_schema

from f1data import layout
from f1data.models import (
    SESSION_ARTIFACTS,
    DriverTelemetry,
    Index,
    Manifest,
    Pointer,
    Standings,
    model_for_artifact,
    telemetry_path,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schema" / f"published-v{layout.FORMAT_VERSION}.schema.json"
)

_GENERATION = "generations/{session_key}/{generation}/"

# The unit a field's name ends in, longest first.
_UNITS = (
    ("_ms_per_lap", "Milliseconds a lap."),
    ("_ms", "Milliseconds."),
    ("_kph", "Kilometres an hour."),
    ("_m", "Metres."),
    ("_pct", "Per cent, from 0 to 100."),
    ("_c", "Degrees Celsius."),
    ("_utc", "UTC, as ISO 8601."),
)


def published_paths() -> dict[str, type]:
    """Every kind of published object by its path under the format's prefix.

    Braces mark the parts of a path that vary.
    """
    paths: dict[str, type] = {
        "index.json": Index,
        "pointers/{session_key}.json": Pointer,
        "standings/{year}.json": Standings,
        f"{_GENERATION}{layout.MANIFEST_NAME}": Manifest,
    }
    for path, model in SESSION_ARTIFACTS.items():
        paths[f"{_GENERATION}{path}"] = model
    paths[f"{_GENERATION}{telemetry_path('{driver_code}')}"] = DriverTelemetry
    return paths


def published_schema() -> dict[str, Any]:
    paths = published_paths()
    models = list(dict.fromkeys(paths.values()))
    references, definitions = models_json_schema(
        [(model, "serialization") for model in models], ref_template="#/$defs/{model}"
    )
    properties = {
        path: {**references[(model, "serialization")], "description": _first_line(model.__doc__)}
        for path, model in paths.items()
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"Formula 1 Data, published format {layout.FORMAT_VERSION}",
        "description": (
            f"Every object published under v{layout.FORMAT_VERSION}/, by its path there. "
            "Braces mark the parts of a path that vary. Generated from f1data/models.py by "
            "`python -m f1data schema`; do not edit. x-decimals on a number, or on an array of "
            "numbers, is how many decimal places it is rounded to."
        ),
        "x-format-version": layout.FORMAT_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
        "$defs": {name: _tidied(definition) for name, definition in definitions["$defs"].items()},
    }


def render_schema() -> str:
    """The schema as the text of the committed file."""
    return json.dumps(published_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_schema(path: Path | None = None) -> bool:
    """Write the schema file. Returns whether it changed."""
    path = path or SCHEMA_PATH
    text = render_schema()
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return True


def validate_published(path: str, payload: Any) -> None:
    """Check a published object, given its path under the format's prefix, against its model.

    Raises ``KeyError`` for a path nothing is published at and pydantic's
    ``ValidationError`` for an object of the wrong shape.
    """
    parts = path.split("/")
    if path == "index.json":
        model: type = Index
    elif len(parts) == 2 and parts[0] == "pointers":
        model = Pointer
    elif len(parts) == 2 and parts[0] == "standings":
        model = Standings
    elif len(parts) >= 4 and parts[0] == "generations":
        found = model_for_artifact("/".join(parts[3:]))
        if found is None:
            raise KeyError(path)
        model = found
    else:
        raise KeyError(path)
    TypeAdapter(model).validate_python(payload, strict=False)


def _tidied(definition: dict[str, Any]) -> dict[str, Any]:
    """A definition with only its own title, and its descriptions as plain text.

    pydantic titles every property after its name (``Lap Time Ms``). A type
    generator takes a title for the name of a type, and would emit an alias
    for every field of every artifact.
    """

    def tidy(node: Any, named: bool) -> Any:
        if isinstance(node, list):
            return [tidy(item, False) for item in node]
        if not isinstance(node, dict):
            return node
        tidied: dict[str, Any] = {}
        for key, value in node.items():
            if key == "title" and not named:
                continue
            if key == "description" and isinstance(value, str):
                tidied[key] = _plain(value)
            elif key == "properties":
                # The keys here are field names, and a field may be called "title".
                tidied[key] = {name: _with_unit(name, tidy(item, False)) for name, item in value.items()}
            else:
                tidied[key] = tidy(value, False)
        return tidied

    return tidy(definition, True)


def _with_unit(name: str, field: dict[str, Any]) -> dict[str, Any]:
    """A field's schema, with its unit as the description when it has none.

    Every field with a unit is named for it (``lap_time_ms``, ``speed_kph``).
    The models describe the fields that need more than that said; the rest
    get the unit spelt out here, so that no number in the schema is bare.
    """
    if "description" in field or "$ref" in field:
        return field
    for suffix, unit in _UNITS:
        if name.endswith(suffix):
            return {**field, "description": unit}
    return field


def _plain(text: str) -> str:
    return " ".join(text.replace("``", "").split())


def _first_line(text: str | None) -> str:
    return _plain((text or "").strip().split("\n\n")[0])
