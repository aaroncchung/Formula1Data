"""The models are the contract: what they refuse, how they round, and that the committed schema is theirs.

docs/architecture-review-findings.md, AR-09: the old contract was a TypeScript
file written by hand and Python dictionaries of anything.
"""

from __future__ import annotations

import json
import typing

import pytest
from pydantic import AfterValidator, BaseModel, ValidationError

from f1data import layout, models
from f1data.cli import main
from f1data.models import (
    SESSION_ARTIFACTS,
    Compound,
    Corner,
    DriverTelemetry,
    Lap,
    Manifest,
    Minisector,
    Standings,
    TelemetryLap,
    WeatherSample,
    artifact_json,
    model_for_artifact,
    telemetry_path,
)
from f1data.schema import SCHEMA_PATH, published_paths, published_schema, render_schema, validate_published

LAP = {
    "driver_code": "AAA", "lap_number": 2, "lap_time_ms": 80_022, "sector_1_ms": 24_000, "sector_2_ms": 32_000,
    "sector_3_ms": 24_022, "compound": "MEDIUM", "tyre_age": 2, "stint": 1, "position": 1, "is_pit_in_lap": False,
    "is_pit_out_lap": False, "is_deleted": False, "is_accurate": True, "track_status": "1",
}


# --- what a model refuses ------------------------------------------------------


def test_a_field_that_is_not_declared_cannot_be_published():
    with pytest.raises(ValidationError, match="session_id"):
        Lap(**LAP, session_id="2026-08-r")


def test_a_field_that_is_declared_cannot_be_left_out():
    with pytest.raises(ValidationError, match="track_status"):
        Lap(**{key: value for key, value in LAP.items() if key != "track_status"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "21.0C", "0 days 00:01:20"])
def test_a_number_that_is_not_one_stops_the_build(value):
    with pytest.raises(ValidationError):
        WeatherSample(
            time_ms=1, lap_number=None, air_temp_c=value, track_temp_c=None, humidity_pct=None,
            rainfall=False, wind_speed_kph=None,
        )


def test_a_time_is_a_whole_number_of_milliseconds():
    with pytest.raises(ValidationError):
        Lap(**{**LAP, "lap_time_ms": 80_022.5})
    assert Lap(**{**LAP, "lap_time_ms": 80_022.0}).lap_time_ms == 80_022


def test_a_compound_is_one_of_f1s_or_null():
    assert Lap(**LAP).compound is Compound.MEDIUM
    for unknown in ("", "None", "nan", "UNKNOWN", "TEST_UNKNOWN", None):
        assert Lap(**{**LAP, "compound": unknown}).compound is None
    assert artifact_json(Lap(**{**LAP, "compound": "intermediate"}))["compound"] == "INTERMEDIATE"


# --- rounding ------------------------------------------------------------------


def test_a_number_is_rounded_to_its_fields_precision_as_it_is_written():
    corner = Corner(number=1, letter=None, x=-3063.957, y=-2208.506, angle=-115.78, distance_m=256.683)

    assert artifact_json(corner) == {
        "number": 1, "letter": None, "x": -3064.0, "y": -2208.5, "angle": -115.8, "distance_m": 256.7,
    }


def test_a_build_a_hair_either_side_of_zero_writes_the_same_bytes():
    """Two platforms differ by about 1e-12 in an interpolated position. Either
    side of zero that used to be 0.0 on one and -0.0 on the other."""
    lap = {
        "lap_number": 1, "start_ms": 0, "time_ms": [0, 1], "speed_kph": [0.0, 0.0], "throttle_pct": [0, 0],
        "brake": [False, False], "rpm": [0, 0], "gear": [0, 0], "drs": None,
    }
    above = TelemetryLap(**lap, distance_m=[1e-12, 4.25], x=[1e-12, None], y=[-0.04, 2.0])
    below = TelemetryLap(**lap, distance_m=[-1e-12, 4.25], x=[-1e-12, None], y=[-0.04, 2.0])

    assert json.dumps(artifact_json(above)) == json.dumps(artifact_json(below))
    assert artifact_json(above)["distance_m"] == [0.0, 4.2]
    assert "-0.0" not in json.dumps(artifact_json(below))


def test_numbers_inside_a_mapping_are_rounded_too():
    sector = Minisector(
        index=1, start_distance_m=0.0, end_distance_m=172.72, midpoint={"x": 1.26, "y": None},
        winner_driver_code="AAA", segment_time_ms=2085.349, gap_to_next_ms=None, driver_times_ms={"AAA": 2085.349},
    )

    assert artifact_json(sector)["driver_times_ms"] == {"AAA": 2085.3}
    assert artifact_json(sector)["midpoint"] == {"x": 1.3, "y": None}


def test_every_number_that_is_not_whole_has_a_stated_precision():
    """A bare float in a session artifact would be written with whatever
    digits the platform's arithmetic left in it."""
    bare = []

    def walk(annotation, where, rounded):
        if typing.get_origin(annotation) is typing.Annotated:
            inner, *metadata = typing.get_args(annotation)
            walk(inner, where, rounded or any(isinstance(item, AfterValidator) for item in metadata))
        elif annotation is float:
            if not rounded:
                bare.append(where)
        else:
            for argument in typing.get_args(annotation):
                walk(argument, where, rounded)

    for name in dir(models):
        model = getattr(models, name)
        if not (isinstance(model, type) and issubclass(model, BaseModel)) or model in (BaseModel, models.Model):
            continue
        # The standings are Jolpica's own figures, published as it gives them.
        if model.__name__.endswith("Standing"):
            continue
        for field_name, field in model.model_fields.items():
            rounded = any(isinstance(item, AfterValidator) for item in field.metadata)
            walk(field.annotation, f"{model.__name__}.{field_name}", rounded)

    assert bare == []


# --- which model is published where --------------------------------------------


def test_every_path_in_a_generation_has_a_model():
    assert model_for_artifact("laps.json") is SESSION_ARTIFACTS["laps.json"]
    assert model_for_artifact("analysis/strategy.json") is models.Strategy
    assert model_for_artifact(telemetry_path("NOR")) is DriverTelemetry
    assert model_for_artifact("manifest.json") is Manifest
    for path in ("telemetry/a/b.json", "telemetry/NOR.txt", "analysis/unknown.json", "sessions/2026-08-r/laps.json"):
        assert model_for_artifact(path) is None, path


# --- the schema ----------------------------------------------------------------


def test_the_committed_schema_is_the_one_the_models_give():
    """When this fails: ``python -m f1data schema``, and commit the file. The
    frontend's types are generated from it, so a shape cannot change here
    without the change reaching them."""
    assert SCHEMA_PATH.name == f"published-v{layout.FORMAT_VERSION}.schema.json"
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render_schema()


def test_the_schema_command_checks_and_rewrites_the_file(tmp_path, monkeypatch, capsys):
    target = tmp_path / "schema" / "published.schema.json"
    monkeypatch.setattr("f1data.schema.SCHEMA_PATH", target)

    with pytest.raises(SystemExit) as missing:
        main(["schema", "--check"])
    with pytest.raises(SystemExit) as written:
        main(["schema"])
    with pytest.raises(SystemExit) as current:
        main(["schema", "--check"])

    assert (missing.value.code, written.value.code, current.value.code) == (1, 0, 0)
    assert target.read_bytes() == render_schema().encode("utf-8")
    assert "out of date" in capsys.readouterr().out


def test_the_schema_names_a_definition_for_every_published_path():
    schema = published_schema()

    assert set(schema["properties"]) == set(published_paths())
    assert schema["required"] == list(schema["properties"])
    for path, entry in schema["properties"].items():
        name = entry["$ref"].removeprefix("#/$defs/")
        assert name in schema["$defs"] and entry["description"], path
    assert schema["properties"]["generations/{session_key}/{generation}/telemetry/{driver_code}.json"]["$ref"].endswith(
        "/DriverTelemetry"
    )
    assert schema["x-format-version"] == layout.FORMAT_VERSION


def test_the_schema_is_plain_enough_to_generate_types_from():
    schema = published_schema()
    lap = schema["$defs"]["Lap"]

    # Every field is required; one that can be null says so.
    assert sorted(lap["required"]) == sorted(lap["properties"])
    assert lap["additionalProperties"] is False
    assert lap["properties"]["lap_time_ms"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
    assert lap["properties"]["compound"]["anyOf"] == [{"$ref": "#/$defs/Compound"}, {"type": "null"}]
    # Closed sets are named enums.
    assert schema["$defs"]["Compound"]["enum"][:3] == ["SOFT", "MEDIUM", "HARD"]
    assert set(schema["$defs"]["CoverageBar"]["enum"]) >= {"position", "classification", "pit_stop_series"}
    # Only definitions carry a title, or a generator names a type after every field.
    titled = [name for name, field in lap["properties"].items() if "title" in field]
    assert titled == [] and lap["title"] == "Lap"
    # Units and precision are said where a reader looks for them.
    assert "x-decimals" in schema["$defs"]["Corner"]["properties"]["x"]
    assert "Milliseconds" in lap["properties"]["lap_time_ms"]["description"]
    # The index is the one object with keys that may be absent.
    assert schema["$defs"]["IndexSession"]["required"] == ["type", "name", "start_time_utc", "in_scope"]
    assert {"session_key", "complete"} <= set(schema["$defs"]["IndexSession"]["properties"])


def test_a_published_object_is_checked_against_the_model_its_path_names():
    validate_published("generations/11315/" + "a" * 64 + "/laps.json", [LAP])
    with pytest.raises(ValidationError):
        validate_published("generations/11315/" + "a" * 64 + "/laps.json", [{**LAP, "session_id": "2026-08-r"}])
    with pytest.raises(KeyError):
        validate_published("sessions/2026-08-r/laps.json", [LAP])
    assert Standings.model_fields["rounds"].description
