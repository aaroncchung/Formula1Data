"""Everything a generation holds, built from one loaded session.

    summary.json  drivers.json  laps.json  results.json  stints.json
    pit-stops.json  weather.json  race-control.json  corners.json  coverage.json
    position-replay.json
    analysis/<name>.json                 ten analyses
    telemetry/index.json                 which laps have telemetry
    telemetry/<driver_code>.json         every lap of one driver, as arrays

Each file is a model from ``f1data/models.py`` written by ``dump_json``:
minified, keys sorted, one newline at the end. Nothing here depends on the
clock, the platform or the order of a dictionary, so the same snapshot and
classification give the same bytes wherever they are built, and with them the
same generation.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from pydantic import BaseModel

from f1data import normalize
from f1data.analyses import position_replay, session_analyses
from f1data.archive import dump_json
from f1data.classification import Classification
from f1data.identity import SessionIdentity
from f1data.models import (
    SESSION_ARTIFACTS,
    TELEMETRY_INDEX_PATH,
    DriverTelemetry,
    TelemetryChannel,
    TelemetryDriverEntry,
    TelemetryIndex,
    TelemetryLap,
    TelemetryLapEntry,
    artifact_json,
    telemetry_path,
)
from f1data.telemetry import (
    MAX_PUBLISHED_SAMPLES_PER_LAP,
    LapSamples,
    SessionTelemetry,
    extract_telemetry,
    nan_as_none,
    thinned_indexes,
)

# A driver's code becomes a file name.
_FILE_SAFE_CODE = re.compile(r"^[A-Z0-9]{1,8}$")


def build_artifacts(
    session: Any,
    identity: SessionIdentity,
    classification: Classification | None,
    extras: dict[str, bytes],
    measurement: dict[str, Any],
) -> dict[str, bytes]:
    """A generation's files by path, from a loaded FastF1 session.

    ``classification`` is today's result from Jolpica, or ``None`` when it has
    none, in which case the result is the order on track and says so.
    ``extras`` are the feeds archived beside the session, and ``measurement``
    its coverage as the build measured it.
    """
    return {
        path: dump_json(artifact_json(artifact))
        for path, artifact in session_artifacts(session, identity, classification, extras, measurement).items()
    }


def session_artifacts(
    session: Any,
    identity: SessionIdentity,
    classification: Classification | None,
    extras: dict[str, bytes],
    measurement: dict[str, Any],
) -> dict[str, BaseModel]:
    """The same, as models."""
    telemetry = extract_telemetry(session)
    codes = normalize.driver_codes(session)
    drivers = normalize.drivers(session, codes)
    laps = normalize.laps(session)
    stints = normalize.stints(laps)
    pit_stops = normalize.pit_stops(session, extras, codes)
    weather = normalize.weather(session, identity.session_type)
    race_control = normalize.race_control(session)
    corners = normalize.circuit_corners(extras, telemetry, laps)
    summary = normalize.summary(identity, session, drivers, laps, weather)

    artifacts: dict[str, Any] = {
        "summary.json": summary,
        "drivers.json": drivers,
        "laps.json": laps,
        "results.json": normalize.results(classification, session, codes),
        "stints.json": stints,
        "pit-stops.json": pit_stops,
        "weather.json": weather,
        "race-control.json": race_control,
        "corners.json": corners,
        "coverage.json": normalize.coverage(measurement),
        "position-replay.json": position_replay(telemetry),
    }
    analyses = session_analyses(summary, drivers, laps, stints, pit_stops, race_control, corners, telemetry)
    artifacts.update({f"analysis/{name}.json": analysis for name, analysis in analyses.items()})
    artifacts.update(telemetry_artifacts(telemetry))
    return {path: _as_model(path, artifact) for path, artifact in artifacts.items()}


def telemetry_artifacts(telemetry: SessionTelemetry) -> dict[str, BaseModel]:
    """The telemetry index and one file per driver, thinned to the published resolution."""
    # Since 2026 the cars have no DRS and the channel is 0 in every sample
    # (AR-18). A channel that never changes says nothing, so it is left out.
    with_drs = len(telemetry.drs_values()) > 1
    with_position = any(lap.has_position for lap in telemetry.laps.values())
    channels = [
        TelemetryChannel.TIME_MS,
        TelemetryChannel.DISTANCE_M,
        TelemetryChannel.SPEED_KPH,
        TelemetryChannel.THROTTLE_PCT,
        TelemetryChannel.BRAKE,
        TelemetryChannel.RPM,
        TelemetryChannel.GEAR,
        *([TelemetryChannel.DRS] if with_drs else []),
        *([TelemetryChannel.X, TelemetryChannel.Y] if with_position else []),
    ]
    files: dict[str, BaseModel] = {}
    entries: list[TelemetryDriverEntry] = []
    for code in telemetry.driver_codes():
        if not _FILE_SAFE_CODE.match(code):
            raise normalize.SessionDataError(f"Driver code {code!r} cannot name a telemetry file")
        laps = telemetry.of_driver(code)
        path = telemetry_path(code)
        published = [_published_lap(lap, with_drs) for lap in laps]
        files[path] = DriverTelemetry(driver_code=code, laps=published)
        entries.append(
            TelemetryDriverEntry(
                driver_code=code,
                path=path,
                laps=[
                    TelemetryLapEntry(
                        lap_number=lap.lap_number,
                        sample_count=len(thinned.time_ms),
                        raw_sample_count=lap.sample_count,
                        has_position=lap.has_position,
                    )
                    for lap, thinned in zip(laps, published)
                ],
            )
        )
    files[TELEMETRY_INDEX_PATH] = TelemetryIndex(
        max_samples_per_lap=MAX_PUBLISHED_SAMPLES_PER_LAP, channels=channels, drivers=entries
    )
    return files


def _published_lap(lap: LapSamples, with_drs: bool) -> TelemetryLap:
    keep = thinned_indexes(lap.sample_count)
    return TelemetryLap(
        lap_number=lap.lap_number,
        start_ms=lap.start_ms,
        time_ms=lap.time_ms[keep].tolist(),
        distance_m=lap.distance_m[keep].tolist(),
        speed_kph=lap.speed_kph[keep].tolist(),
        throttle_pct=_whole(lap.throttle_pct[keep]),
        brake=lap.brake[keep].tolist(),
        rpm=_whole(lap.rpm[keep]),
        gear=lap.gear[keep].tolist(),
        drs=lap.drs[keep].tolist() if with_drs else None,
        x=nan_as_none(lap.x[keep]) if lap.x is not None else None,
        y=nan_as_none(lap.y[keep]) if lap.y is not None else None,
    )


def _whole(values: np.ndarray) -> list[int]:
    """To the nearest whole number. The car sends whole numbers; only merged samples have fractions."""
    return np.rint(values).astype(np.int64).tolist()


def _as_model(path: str, artifact: Any) -> BaseModel:
    """Lists of rows become their artifact's model, which checks them once more as a whole."""
    if isinstance(artifact, BaseModel):
        return artifact
    return SESSION_ARTIFACTS[path].model_validate(artifact)
