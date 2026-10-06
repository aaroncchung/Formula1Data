"""A whole generation built from one session: what is in it, and that it is the contract.

Each file is checked against its model again after it has been written, read
back as a stranger would read it. The analyses are checked to have read every
sample, not the thinned copy that is published
(docs/architecture-review-findings.md, AR-05, AR-09, AR-11).
"""

from __future__ import annotations

import hashlib
import json

import pytest

from backend.app.analysis.advanced import (
    calculate_car_performance,
    calculate_corner_analysis,
    calculate_track_dominance,
)
from backend.app.analysis.position_replay import REPLAY_INTERVAL_MS, build_position_replay
from f1data import normalize
from f1data.analyses import LapRows, position_replay, sample_rows
from f1data.artifacts import build_artifacts, telemetry_artifacts
from f1data.coverage import apply_classification, measure_coverage
from f1data.extras import CIRCUIT_INFO
from f1data.models import SESSION_ARTIFACTS, artifact_json, model_for_artifact
from f1data.publish import upload_generation
from f1data.store import MemoryStore
from f1data.telemetry import MAX_PUBLISHED_SAMPLES_PER_LAP, extract_telemetry
from tests.race import IDENTITY, LAPS, classification, extras, index_laps, make_race


def built(session=None, official=classification, found=None):
    session = session or make_race()
    found = extras() if found is None else found
    result = official() if official else None
    measurement = measure_coverage(session, "R", found)
    if result is not None:
        measurement = apply_classification(measurement, result.laps_by_number)
    return build_artifacts(session, IDENTITY, result, found, measurement)


def read(files, path):
    return json.loads(files[path])


def flat_rows(telemetry):
    """Every sample of the session as one list of rows: what the analyses were written to take."""
    return [row for lap in telemetry.laps.values() for row in sample_rows(lap)]


# --- what a generation holds ---------------------------------------------------


def test_a_generation_holds_every_artifact_and_one_telemetry_file_per_driver():
    files = built()

    # Every artifact but the one made for practice sessions only.
    assert set(files) == (set(SESSION_ARTIFACTS) - {"analysis/pace-prediction.json"}) | {
        "telemetry/AAA.json",
        "telemetry/BBB.json",
        "telemetry/CCC.json",
    }
    assert all(data.endswith(b"\n") and b"\r" not in data and b"\n" not in data[:-1] for data in files.values())


def test_every_file_is_what_its_model_says_when_read_back():
    files = built()

    for path, data in files.items():
        model = model_for_artifact(path)
        assert model is not None, path
        # Reading it into the model and writing it again changes nothing:
        # every number is already at its stated precision.
        assert artifact_json(model.model_validate(json.loads(data))) == json.loads(data), path


def test_nothing_in_a_generation_is_a_stand_in_for_a_missing_value():
    everything = b"".join(built().values()).decode()

    for forbidden in ("NaN", '"nan"', '"None"', '"NaT"', "0 days", "Infinity", "session_id", "-0.0,", "-0.0]"):
        assert forbidden not in everything, forbidden


def test_nothing_in_a_generation_comes_from_the_calendar():
    """A round number moves when the calendar changes (AR-20), so it is looked up in the index."""
    files = built()

    assert b'"round"' not in b"".join(files.values())
    assert read(files, "summary.json")["meeting"] == IDENTITY.meeting_name


def test_two_builds_of_the_same_inputs_are_the_same_bytes_and_one_generation():
    first, second = built(), built()

    assert first == second
    one, other = MemoryStore(), MemoryStore()
    assert upload_generation(one, IDENTITY, first) == upload_generation(other, IDENTITY, second)


def test_a_build_does_not_depend_on_the_order_the_feeds_list_the_drivers_in():
    shuffled = make_race()
    shuffled.car_data = dict(reversed(list(shuffled.car_data.items())))
    shuffled.pos_data = dict(reversed(list(shuffled.pos_data.items())))

    assert built(shuffled) == built()


# --- telemetry -----------------------------------------------------------------


def test_telemetry_is_published_per_driver_as_arrays_thinned_to_the_limit():
    files = built()
    index = read(files, "telemetry/index.json")
    driver = read(files, "telemetry/BBB.json")

    assert index["max_samples_per_lap"] == MAX_PUBLISHED_SAMPLES_PER_LAP
    assert [entry["driver_code"] for entry in index["drivers"]] == ["AAA", "BBB", "CCC"]
    entry = index["drivers"][1]
    assert entry["path"] == "telemetry/BBB.json"
    # Enough to offer the laps to choose from, without reading laps.json.
    timed = {lap["lap_number"]: lap for lap in read(files, "laps.json") if lap["driver_code"] == "BBB"}
    laps = index_laps(entry)
    assert [(lap["lap_time_ms"], lap["compound"]) for lap in laps] == [
        (timed[lap["lap_number"]]["lap_time_ms"], timed[lap["lap_number"]]["compound"]) for lap in laps
    ]
    assert laps[1]["lap_time_ms"] and laps[1]["compound"] == "MEDIUM"
    assert entry["lap_number"] == list(range(1, LAPS + 1))
    assert set(entry["sample_count"]) == {MAX_PUBLISHED_SAMPLES_PER_LAP}
    assert all(lap["raw_sample_count"] > 2 * lap["sample_count"] for lap in laps)

    lap = driver["laps"][1]
    arrays = [name for name, value in lap.items() if isinstance(value, list)]
    assert sorted(arrays) == sorted(index["channels"])
    assert {len(lap[name]) for name in arrays} == {MAX_PUBLISHED_SAMPLES_PER_LAP}
    # Both ends of the lap survive the thinning.
    full = extract_telemetry(make_race()).laps[("BBB", 2)]
    assert (lap["time_ms"][0], lap["time_ms"][-1]) == (0, int(full.time_ms[-1]))
    assert lap["start_ms"] == full.start_ms
    assert all(isinstance(value, int) for name in ("time_ms", "rpm", "gear", "throttle_pct") for value in lap[name])
    assert all(round(value, 1) == value for name in ("distance_m", "speed_kph", "x", "y") for value in lap[name])


def test_drs_is_left_out_when_it_never_changes_and_kept_when_it_does():
    """2026 has no DRS and the channel is 0 in every sample (AR-18)."""
    without = built()
    kept = built(make_race(drs=True))

    assert "drs" not in read(without, "telemetry/index.json")["channels"]
    assert read(without, "telemetry/AAA.json")["laps"][3]["drs"] is None
    assert "drs" in read(kept, "telemetry/index.json")["channels"]
    assert set(read(kept, "telemetry/AAA.json")["laps"][3]["drs"]) == {0, 12}


def test_a_driver_code_that_cannot_name_a_file_stops_the_build():
    session = make_race()
    session.laps["Driver"] = session.laps["Driver"].replace("CCC", "../C")

    with pytest.raises(normalize.SessionDataError, match="cannot name a telemetry file"):
        telemetry_artifacts(extract_telemetry(session), normalize.laps(session))


# --- the analyses read every sample --------------------------------------------


def test_handing_the_analyses_telemetry_by_lap_changes_nothing_they_compute():
    """They are given the laps they ask for instead of 25,000 rows here, and
    750,000 for a race. What they return must be what the rows would give."""
    session = make_race()
    telemetry = extract_telemetry(session)
    laps = [artifact_json(lap) for lap in normalize.laps(session)]
    drivers = [{"code": code, "team": {"name": "Alpha Racing"}} for code in ("AAA", "BBB", "CCC")]
    rows, by_lap = flat_rows(telemetry), LapRows(telemetry)
    assert len(rows) > 20_000

    assert calculate_track_dominance("s", laps, by_lap) == calculate_track_dominance("s", laps, rows)
    assert calculate_corner_analysis("s", laps, by_lap) == calculate_corner_analysis("s", laps, rows)
    assert calculate_car_performance("s", laps, by_lap, drivers) == calculate_car_performance("s", laps, rows, drivers)


def test_the_analyses_see_every_sample_not_the_published_three_hundred():
    files = built()
    full = extract_telemetry(make_race())

    dominance = read(files, "analysis/track-dominance.json")
    lap = next(row for row in dominance["representative_laps"] if row["driver_code"] == "BBB")
    samples = full.laps[("BBB", lap["lap_number"])]

    assert samples.sample_count > 2 * MAX_PUBLISHED_SAMPLES_PER_LAP
    # A driver's minisectors add up to the lap, to the rounding of each.
    covered = sum(sector["driver_times_ms"]["BBB"] for sector in dominance["minisectors"])
    assert covered == pytest.approx(lap["lap_time_ms"], abs=0.1 * dominance["minisector_count"])
    # The top speed the car reported is in the published profile, though the
    # thinned copy of that lap may have dropped the sample.
    profile = next(row for row in read(files, "analysis/car-performance.json")["drivers"] if row["driver_code"] == "BBB")
    assert profile["max_speed_kph"] == float(full.laps[("BBB", profile["lap_number"])].speed_kph.max())


def test_the_replay_is_what_every_sample_of_the_session_would_give():
    telemetry = extract_telemetry(make_race())

    replay = artifact_json(position_replay(telemetry))
    frames = build_position_replay("s", flat_rows(telemetry))

    assert replay["interval_ms"] == REPLAY_INTERVAL_MS
    assert replay["time_ms"] == [frame["timestamp_ms"] for frame in frames]
    assert [driver["driver_code"] for driver in replay["drivers"]] == ["AAA", "BBB", "CCC"]
    for driver in replay["drivers"]:
        for index, frame in enumerate(frames):
            position = next((item for item in frame["positions"] if item["driver_code"] == driver["driver_code"]), None)
            for channel in ("x", "y", "speed_kph", "distance_m"):
                expected = round(position[channel], 1) if position else None
                assert driver[channel][index] == expected, (driver["driver_code"], index, channel)
    # The lap the race has reached never goes backwards, and ends on the last.
    reached = replay["lap_number"]
    assert reached[0] == 1 and reached == sorted(reached) and reached[-1] == LAPS


# --- sessions that are short of something ---------------------------------------


def test_a_session_whose_position_feed_stops_is_built_with_what_there_is():
    """The 2026 Monaco race: F1's position feed stops in lap 5 of 78."""
    whole = make_race()
    stops_in = whole.laps.query("Driver == 'AAA' and LapNumber == 5").iloc[0]
    stopped = (stops_in["LapStartTime"] + (stops_in["Time"] - stops_in["LapStartTime"]) / 2).total_seconds()

    files = built(make_race(position_until=stopped))

    replay = read(files, "position-replay.json")
    assert replay["time_ms"] and replay["time_ms"][-1] < 1000 * stopped
    assert max(number for number in replay["lap_number"] if number) < 5
    index = read(files, "telemetry/index.json")
    located = {lap["lap_number"] for entry in index["drivers"] for lap in index_laps(entry) if lap["has_position"]}
    assert located == {1, 2, 3, 4}
    late = read(files, "telemetry/BBB.json")["laps"][7]
    assert late["x"] is None and late["y"] is None and len(late["speed_kph"]) == MAX_PUBLISHED_SAMPLES_PER_LAP
    # The analyses that place things on a map say that they cannot.
    dominance = read(files, "analysis/track-dominance.json")
    assert dominance["minisector_count"] == 25 and dominance["minisectors"][0]["winner_driver_code"]
    coverage = read(files, "coverage.json")
    assert {(item["bar"], item["driver"]) for item in coverage["shortfalls"]} >= {("position", "AAA"), ("position", "BBB")}


def test_analyses_that_need_position_say_when_there_is_none():
    session = make_race()
    session.pos_data = {}

    files = built(session, found=extras(corners=False))

    assert read(files, "position-replay.json") == {"interval_ms": REPLAY_INTERVAL_MS, "time_ms": [], "lap_number": [], "drivers": []}
    assert "x" not in read(files, "telemetry/index.json")["channels"]
    dominance = read(files, "analysis/track-dominance.json")
    assert dominance["minisectors"][3]["midpoint"] == {"x": None, "y": None}
    assert any("no position data" in caveat for caveat in dominance["caveats"])
    corners = read(files, "analysis/corner-analysis.json")
    assert corners["corner_source"] == "inferred" and corners["corners"]
    assert any("no position data" in caveat for caveat in corners["caveats"])


def test_official_corners_are_used_when_archived_and_inferred_ones_when_not():
    official = read(built(), "analysis/corner-analysis.json")
    inferred = read(built(found=extras(corners=False)), "analysis/corner-analysis.json")

    assert official["corner_source"] == "official"
    assert [(corner["corner_number"], corner["letter"]) for corner in official["corners"]] == [(1, None), (2, "A"), (3, None)]
    assert all(len(corner["drivers"]) == 3 for corner in official["corners"])
    assert inferred["corner_source"] == "inferred"
    assert all(corner["letter"] is None for corner in inferred["corners"])
    assert read(built(found=extras(corners=False)), "corners.json")["corners"] == []


def test_corners_that_do_not_lie_on_the_track_are_not_what_the_laps_are_segmented_by():
    found = extras()
    archived = json.loads(found[CIRCUIT_INFO])
    archived["corners"] = [{**corner, "x": corner["x"] * 1.12, "y": corner["y"] * 1.12} for corner in archived["corners"]]
    found[CIRCUIT_INFO] = json.dumps(archived).encode()

    files = built(found=found)

    assert read(files, "corners.json")["fits_track"] is False
    analysis = read(files, "analysis/corner-analysis.json")
    assert analysis["corner_source"] == "inferred"
    assert "do not lie on the line of the lap" in analysis["caveats"][-1] and "m off it" in analysis["caveats"][-1]
    assert read(built(), "corners.json")["fits_track"] is True


def test_a_race_with_no_classification_is_built_with_a_provisional_result():
    """Jolpica has had no result for the whole retry window."""
    session = make_race()
    # What FastF1 holds when Jolpica has nothing: the driver list and no result.
    for column in ("Position", "GridPosition", "Points", "Laps"):
        session.results[column] = float("nan")
    for column in ("ClassifiedPosition", "Status", "Time"):
        session.results[column] = None

    files = built(session, official=None)

    results = read(files, "results.json")
    assert [row["driver_code"] for row in results] == ["BBB", "AAA", "CCC"]
    assert all(row["provisional"] and row["points"] is None for row in results)
    coverage = read(files, "coverage.json")
    assert coverage["complete"] is False
    assert {item["bar"] for item in coverage["shortfalls"]} >= {"classification"}
    # Everything else is built as usual.
    assert set(files) == set(built())
    assert read(files, "pit-stops.json")[0]["stationary_ms"] == 2400
    assert read(files, "analysis/strategy.json")["pit_loss"]["stop_count"] == 1


def test_an_analysis_does_not_repeat_other_artifacts():
    """The old strategy file carried every stint, every stop and every race
    control message again: 68 kB of a race's 62."""
    strategy = read(built(), "analysis/strategy.json")

    assert sorted(strategy) == [
        "caveats", "compound_usage", "pit_lane_time", "pit_loss", "pit_loss_estimate_ms", "undercut_overcut",
    ]
    assert strategy["compound_usage"] == {"MEDIUM": 3, "HARD": 1, "UNKNOWN": 1}


def test_the_practice_only_analysis_is_published_for_practice_only():
    """It answers "not available" for anything else, and a file that never has
    anything in it is not published."""
    from dataclasses import replace

    session = make_race()
    found = extras()
    measurement = measure_coverage(session, "FP2", found)
    practice = replace(IDENTITY, session_type="FP2", session_name="Practice 2")

    assert "analysis/pace-prediction.json" not in built()
    files = build_artifacts(session, practice, None, found, measurement)
    assert read(files, "analysis/pace-prediction.json")["session_type"] == "Practice 2"


def test_the_generation_is_named_by_what_is_in_it():
    files = built()
    store = MemoryStore()

    generation, _ = upload_generation(store, IDENTITY, files)

    manifest = json.loads(store.get(f"v2/generations/{IDENTITY.session_key}/{generation}/manifest.json").data)
    assert manifest["format_version"] == 2 and "schema_version" not in manifest
    assert [item["path"] for item in manifest["files"]] == sorted(files)
    assert all(hashlib.sha256(files[item["path"]]).hexdigest() == item["sha256"] for item in manifest["files"])
