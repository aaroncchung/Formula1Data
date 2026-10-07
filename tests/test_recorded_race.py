"""The build, on recorded races from the source archive.

    F1DATA_TEST_ARCHIVE=<a directory store, or r2> python -m pytest tests/test_recorded_race.py -s

Skipped unless the variable is set. Nothing here touches the network: the
builds are ``Builder.build`` itself, run on the archive with every host
refused, and what a run gathers first (the calendar row, and the Austrian
race's result with its first-lap times) is stood in for (tests/recorded.py).

Four things are checked that only real data can check:

* The telemetry this build makes is FastF1's own, sample for sample.
* A golden build of the 2026 Austrian GP (session 11315): the figures a
  regression would move, and a checksum of every file
  (docs/architecture-review-findings.md, AR-08).
* Every feed has a coverage bar that notices it missing: each of the eleven
  FastF1 requests and both extras is removed in turn, for the session and
  where it applies for a single driver, and the session has to come out
  incomplete (section 6, rule 6). ``-s`` prints the table.

* What F1's feeds have been seen to do that a stand-in would not think of:
  rows FastF1 adds for cars missing from the car feed (the 2026 Belgian GP),
  pit stops reported late and with no lap (the 2026 Australian GP), a car
  whose data stops before its lap does (the 2025 São Paulo sprint).

To record the golden file again after an intended change:

    F1DATA_WRITE_FIXTURES=1 F1DATA_TEST_ARCHIVE=... python -m pytest tests/test_recorded_race.py
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from backend.app.analysis.advanced import calculate_car_performance, calculate_track_dominance
from backend.app.analysis.position_replay import build_position_replay
from f1data import layout, normalize
from f1data.analyses import LapRows, position_replay, sample_rows
from f1data.artifacts import build_artifacts
from f1data.classification import merge_into_session
from f1data.coverage import apply_classification, evaluate_coverage, measure_coverage, sent_by_f1
from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES, parse_pit_stop_series
from f1data.models import artifact_json, model_for_artifact
from f1data.publish import upload_generation
from f1data.store import MemoryStore
from f1data.telemetry import MAX_PUBLISHED_SAMPLES_PER_LAP, extract_telemetry
from tests.race import index_laps
from tests.recorded import (
    ARCHIVE_VARIABLE,
    FEED_FILES,
    FIXTURES,
    PER_DRIVER_FEEDS,
    archive_store,
    build_offline,
    classified_laps,
    load_offline,
    recorded_classification,
    restore,
    without,
    without_pit_stops_of,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get(ARCHIVE_VARIABLE),
    reason=f"set {ARCHIVE_VARIABLE} to a store holding the 2026 archive (a directory, or r2)",
)

AUSTRIA = 11315
MONACO = 11299
HUNGARY = 11342
BELGIUM = 11334
AUSTRALIA = 11234
SAO_PAULO_SPRINT_2025 = 9864
CANADA_2025 = 9963
AZERBAIJAN = 11377
GOLDEN = FIXTURES / f"golden-{AUSTRIA}.json"
# The driver each single-driver removal is made for: Hamilton, who finished
# and stopped three times.
ONE_DRIVER = ("44", "HAM")
FEED_TABLE: list[tuple[str, str, str]] = []


@pytest.fixture(scope="module")
def austria(tmp_path_factory):
    base = tmp_path_factory.mktemp("austria") / "cache"
    store = archive_store()
    snapshot, extras = restore(store, AUSTRIA, base)
    return SimpleNamespace(
        store=store, snapshot=snapshot, extras=extras, base=base, session=load_offline(snapshot, base)
    )


@pytest.fixture(scope="module")
def telemetry(austria):
    return extract_telemetry(austria.session)


def build(recorded, official):
    """``Builder.build`` on the archived snapshot, with ``official`` as the result that was gathered."""
    return build_offline(recorded.store, recorded.snapshot, official)


@pytest.fixture(scope="module")
def generation(austria):
    started = time.perf_counter()
    files = build(austria, recorded_classification(AUSTRIA))
    return SimpleNamespace(files=files, seconds=time.perf_counter() - started)


@pytest.fixture(scope="module", autouse=True)
def feed_table():
    yield
    if FEED_TABLE:
        width = max(len(row[0]) for row in FEED_TABLE)
        print("\n\nRemoved from the recorded race".ljust(width + 4) + "For".ljust(12) + "What the bars said")
        for removed, scope, outcome in FEED_TABLE:
            print(f"{removed.ljust(width + 2)}{scope.ljust(12)}{outcome}")


def read(files, path):
    return json.loads(files[path])


# --- the telemetry is FastF1's --------------------------------------------------


def test_each_laps_telemetry_is_what_fastf1s_own_per_lap_call_returns(austria, telemetry):
    """``Lap.get_telemetry`` takes about 0.3 s a lap, so a spread of laps is
    compared: every fortieth, which takes in first laps, pit laps and last
    laps. The whole race was compared once, by the same code, with the same
    result: no sample of any channel differs at all."""
    channels = {
        "distance_m": "Distance", "speed_kph": "Speed", "throttle_pct": "Throttle", "rpm": "RPM",
        "gear": "nGear", "brake": "Brake", "drs": "DRS", "x": "X", "y": "Y",
    }
    compared = 0
    for position, (_, lap) in enumerate(austria.session.laps.iterlaps()):
        if position % 40:
            continue
        mine = telemetry.laps[(str(lap["Driver"]), int(lap["LapNumber"]))]
        theirs = lap.get_telemetry()
        where = f"{lap['Driver']} lap {int(lap['LapNumber'])}"
        assert len(theirs) == mine.sample_count, where
        assert (theirs["Time"].to_numpy().astype("int64") == mine.time_ms * 1_000_000).all(), where
        for name, column in channels.items():
            assert (getattr(mine, name).astype(float) == theirs[column].to_numpy().astype(float)).all(), (where, name)
        compared += 1
    assert compared >= 30


def test_no_lap_is_thinned_before_the_analyses_see_it(austria, telemetry):
    assert len(telemetry.laps) == len(austria.session.laps) == 1339
    assert all(lap.has_position for lap in telemetry.laps.values())
    counts = [lap.sample_count for lap in telemetry.laps.values()]
    assert sum(counts) == 757_210 and min(counts) > MAX_PUBLISHED_SAMPLES_PER_LAP
    assert telemetry.drs_values() == {0}


def test_telemetry_by_lap_gives_the_analyses_what_every_row_would(austria, telemetry):
    """The whole race as 757,210 rows, once, to show the shortcut is not one."""
    laps = [artifact_json(lap) for lap in normalize.laps(austria.session)]
    drivers = [{"code": code, "team": {"name": "Any"}} for code in telemetry.driver_codes()]
    rows = [row for lap in telemetry.laps.values() for row in sample_rows(lap)]
    by_lap = LapRows(telemetry)

    assert calculate_track_dominance("s", laps, by_lap) == calculate_track_dominance("s", laps, rows)
    assert calculate_car_performance("s", laps, by_lap, drivers) == calculate_car_performance("s", laps, rows, drivers)
    replay = artifact_json(position_replay(telemetry))
    frames = build_position_replay("s", rows)
    assert replay["time_ms"] == [frame["timestamp_ms"] for frame in frames]
    for driver in replay["drivers"]:
        expected = [
            next((round(p["x"], 1) for p in frame["positions"] if p["driver_code"] == driver["driver_code"]), None)
            for frame in frames
        ]
        assert driver["x"] == expected, driver["driver_code"]


# --- the golden race ------------------------------------------------------------


def test_the_austrian_race_builds_in_well_under_the_time_one_lap_used_to_take_per_driver(generation):
    # About 10 s here against six minutes before. The limit is the target, not the time.
    assert generation.seconds < 90


def test_the_austrian_race_in_figures(generation):
    files = generation.files

    summary = read(files, "summary.json")
    assert (summary["session_key"], summary["lap_count"], summary["driver_count"]) == (AUSTRIA, 1339, 22)
    assert (summary["meeting"], summary["session_type"], summary["circuit"]) == ("Austrian Grand Prix", "R", "Spielberg")
    assert summary["clock_zero_utc"] == "2026-06-28T12:06:12.076Z"
    assert len(read(files, "laps.json")) == 1339
    assert len(read(files, "drivers.json")) == 22

    results = read(files, "results.json")
    assert [(row["position"], row["driver_code"], row["time_ms"], row["gap_ms"], row["laps"]) for row in results[:4]] == [
        (1, "RUS", 5_197_979, None, 71),
        (2, "VER", None, 1_611, 71),
        (3, "ANT", None, 1_986, 71),
        (4, "PIA", None, 21_809, 71),
    ]
    assert [row["driver_code"] for row in results[-4:]] == ["STR", "SAI", "PER", "BOT"]
    # Ninth was a lap down and took the flag 15.3 s after the winner: laps down, and no gap.
    assert {key: results[8][key] for key in ("driver_code", "gap_ms", "laps_down", "behind_at_flag_ms", "laps")} == {
        "driver_code": "LAW", "gap_ms": None, "laps_down": 1, "behind_at_flag_ms": 15_334, "laps": 70,
    }
    assert [row["laps_down"] for row in results] == [None] * 8 + [1] * 7 + [2, 2, 3] + [None] * 4
    assert sum(row["points"] for row in results) == 101 and not any(row["provisional"] for row in results)

    strategy = read(files, "analysis/strategy.json")
    assert strategy["pit_loss_estimate_ms"] == 21_282.0
    assert (strategy["pit_loss"]["qualifying_stop_count"], strategy["pit_loss"]["stop_count"]) == (33, 44)
    assert strategy["pit_loss"]["spread_ms"] == 834.7
    assert strategy["pit_lane_time"] == {
        "median_ms": 21_574.0, "fastest_ms": 21_042, "slowest_ms": 28_879, "timed_stop_count": 41, "stop_count": 44,
    }
    assert strategy["compound_usage"] == {"HARD": 24, "MEDIUM": 31, "SOFT": 8}
    assert "pit_stops" not in strategy and "race_control_overlays" not in strategy

    stops = read(files, "pit-stops.json")
    assert len(stops) == 44 and sum(stop["stationary_ms"] is not None for stop in stops) == 36
    first = next(stop for stop in stops if (stop["driver_code"], stop["lap_number"]) == ("HAM", 12))
    assert (first["duration_ms"], first["pit_lane_ms"], first["stationary_ms"]) == (21_298, 21_369, 2_400)
    # Aston Martin and Williams are not in F1's pit-stop feed for this race.
    assert {stop["driver_code"] for stop in stops if stop["duration_ms"] and stop["stationary_ms"] is None} == {"ALO", "STR", "ALB"}

    dominance = read(files, "analysis/track-dominance.json")
    assert (dominance["minisector_count"], dominance["excluded_drivers"]) == (25, ["BOT"])
    assert len(dominance["representative_laps"]) == 21
    corners = read(files, "analysis/corner-analysis.json")
    assert corners["corner_source"] == "official"
    assert [corner["corner_number"] for corner in corners["corners"]] == list(range(1, 11))
    circuit = read(files, "corners.json")
    assert (circuit["distance_source"], circuit["fits_track"], circuit["off_track_m"]) == ("archive", True, 5.9)
    assert circuit["reference_lap"] == {"driver_code": "ANT", "lap_number": 59, "length_m": 4290.5}
    assert read(files, "coverage.json")["complete"] is True


def test_the_austrian_races_files(generation):
    files = generation.files
    index = read(files, "telemetry/index.json")

    # 21 artifacts, the telemetry index and 22 drivers. The manifest makes 45 objects.
    assert len(files) == 43 and "analysis/pace-prediction.json" not in files
    assert sorted(path for path in files if path.startswith("telemetry/") and path != "telemetry/index.json") == [
        f"telemetry/{code}.json"
        for code in sorted(
            "ALB ALO ANT BEA BOR BOT COL GAS HAD HAM HUL LAW LEC LIN NOR OCO PER PIA RUS SAI STR VER".split()
        )
    ]
    assert "drs" not in index["channels"]
    assert sum(len(entry["lap_number"]) for entry in index["drivers"]) == 1339
    assert sum(sum(entry["raw_sample_count"]) for entry in index["drivers"]) == 757_210
    assert sum(sum(entry["sample_count"]) for entry in index["drivers"]) == 1339 * 300
    # The index is enough to offer the laps to choose from.
    fastest = min(
        (lap["lap_time_ms"], entry["driver_code"], lap["lap_number"], lap["compound"])
        for entry in index["drivers"]
        for lap in index_laps(entry)
        if lap["lap_time_ms"]
    )
    assert fastest == (70_374, "ANT", 59, "HARD")
    # 266 kB in the old format, where it listed a file for every lap.
    assert len(files["telemetry/index.json"]) < 80_000
    replay = read(files, "position-replay.json")
    assert (len(replay["time_ms"]), len(replay["drivers"]), replay["lap_number"][-1]) == (1054, 22, 71)
    # 108 MB in 1,342 files in the old format.
    assert sum(len(data) for data in files.values()) < 25_000_000
    assert max(len(data) for data in files.values()) < 1_200_000
    for path, data in files.items():
        assert artifact_json(model_for_artifact(path).model_validate(json.loads(data))) == json.loads(data), path


def test_the_austrian_race_is_the_same_bytes_as_when_the_golden_file_was_recorded(generation, monkeypatch):
    """Every file's checksum. A change to an analysis, to the rounding or to
    the normaliser moves at least one, and this names the files. Built on
    another platform it is also the check that a build does not depend on the
    platform."""
    built = {
        path: {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
        for path, data in sorted(generation.files.items())
    }
    # The pipeline version is in the manifest; held still so that a bump alone moves nothing.
    monkeypatch.setattr(layout, "PIPELINE_VERSION", 1)
    name, _ = upload_generation(MemoryStore(), SimpleNamespace(session_key=AUSTRIA, to_json=dict), generation.files)
    recorded = {"generation": name, "files": built}
    if os.environ.get("F1DATA_WRITE_FIXTURES") == "1":
        with GOLDEN.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(recorded, handle, indent=1, sort_keys=True)
            handle.write("\n")

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    moved = sorted(path for path in set(built) | set(golden["files"]) if built.get(path) != golden["files"].get(path))
    assert moved == []
    assert name == golden["generation"]


def test_a_second_build_of_the_same_snapshot_is_the_same_generation(austria, generation):
    again = build(austria, recorded_classification(AUSTRIA))

    assert again == generation.files
    one, other = MemoryStore(), MemoryStore()
    assert upload_generation(one, austria.snapshot.identity, again) == upload_generation(
        other, austria.snapshot.identity, generation.files
    )


def test_the_order_on_track_from_the_timing_is_the_official_result_to_the_millisecond(austria):
    """What is published when Jolpica has no classification. For this race it
    is the classification: all 22 places, laps and gaps."""
    codes = normalize.driver_codes(austria.session)

    official = normalize.results(recorded_classification(AUSTRIA), austria.session, codes)
    provisional = normalize.results(None, austria.session, codes)

    figures = lambda row: (row.position, row.driver_code, row.laps, row.gap_ms, row.laps_down, row.behind_at_flag_ms)
    assert [figures(row) for row in provisional] == [figures(row) for row in official]
    assert all(row.provisional and row.points is None for row in provisional)


def test_a_race_with_no_classification_builds_whole(austria):
    """Jolpica has had no result for the whole retry window, so the snapshot's
    record has no classified laps either: it was fetched without them."""
    unclassified = {
        code: {**driver, "classified_laps": None} for code, driver in austria.snapshot.coverage["drivers"].items()
    }
    fetched_without_a_result = replace(
        austria.snapshot, coverage={**austria.snapshot.coverage, "drivers": unclassified}
    )

    files = build(SimpleNamespace(store=austria.store, snapshot=fetched_without_a_result), None)

    assert read(files, "results.json")[0] == {
        "position": 1, "driver_code": "RUS", "classified_position": None, "status": None, "points": None,
        "grid": None, "time_ms": None, "gap_ms": None, "laps_down": None, "behind_at_flag_ms": None,
        "laps": 71, "provisional": True,
    }
    coverage = read(files, "coverage.json")
    assert coverage["complete"] is False and {item["bar"] for item in coverage["shortfalls"]} == {"classification"}
    assert len(files) == 43


def test_corners_the_build_places_itself_land_where_fastf1_put_them(austria, telemetry):
    """The archive has these corners with distances. Taken away, the build's
    own come within a few metres: both read them off one lap's telemetry."""
    archived = json.loads(austria.extras[CIRCUIT_INFO])
    bare = {**austria.extras, CIRCUIT_INFO: json.dumps(
        {**archived, "corners": [{**corner, "distance_m": None} for corner in archived["corners"]]}
    ).encode()}
    laps = normalize.laps(austria.session)

    placed = normalize.circuit_corners(bare, telemetry, laps)

    assert placed.distance_source.value == "telemetry" and placed.reference_lap.length_m > 4000
    for corner, theirs in zip(placed.corners, archived["corners"]):
        assert corner.distance_m == pytest.approx(theirs["distance_m"], abs=15.0), corner.number


# --- every feed has a bar -------------------------------------------------------


def shortfalls_without(austria, tmp_path, bar, driver_number=None):
    """The bars the session falls short of with one feed taken out of its cache."""
    session = load_offline(austria.snapshot, without(austria.base, austria.snapshot, tmp_path / "cache", bar, driver_number))
    measurement = apply_classification(
        measure_coverage(session, "R", austria.extras), classified_laps(austria.snapshot)
    )
    return evaluate_coverage(measurement)


def test_the_recorded_race_meets_every_bar_before_anything_is_removed(austria):
    measurement = apply_classification(
        measure_coverage(austria.session, "R", austria.extras), classified_laps(austria.snapshot)
    )

    assert evaluate_coverage(measurement) == []


@pytest.mark.parametrize("bar", sorted(FEED_FILES))
def test_a_session_without_one_of_the_eleven_feeds_is_incomplete(austria, tmp_path, bar):
    found = shortfalls_without(austria, tmp_path, bar)

    bars = sorted({item.bar for item in found})
    FEED_TABLE.append((FEED_FILES[bar], "session", f"incomplete: {len(found)} shortfall(s) on {', '.join(bars)}"))
    assert bar in bars


@pytest.mark.parametrize("bar", PER_DRIVER_FEEDS)
def test_a_session_without_one_drivers_share_of_a_feed_is_incomplete_and_names_the_driver(austria, tmp_path, bar):
    number, code = ONE_DRIVER

    found = shortfalls_without(austria, tmp_path, bar, driver_number=number)

    # FastF1 loads nothing for a driver who is not in F1's driver list, and with
    # Jolpica refused as well, as it is here, nothing gives them a code. They
    # are then known as the classification knows them: by number.
    who = {code, f"#{number}"}
    named = sorted({item.bar for item in found if item.driver in who})
    FEED_TABLE.append((FEED_FILES[bar], code, f"incomplete: {code} short on {', '.join(named)}"))
    assert bar in named
    # Nobody else is blamed for it.
    assert {item.driver for item in found} <= who


def build_without(austria, tmp_path, bar, driver_number=None, damage=None):
    """The generation of the recorded race with one feed taken out of its cache, built as a run builds it."""
    cache = without(austria.base, austria.snapshot, tmp_path / "cache", bar, driver_number)
    if damage is not None:
        damage(cache / austria.snapshot.identity.archive_path)
    session = load_offline(austria.snapshot, cache)
    official = recorded_classification(AUSTRIA)
    measurement = apply_classification(measure_coverage(session, "R", austria.extras), official.laps_by_number)
    merge_into_session(session, official)
    return build_artifacts(session, austria.snapshot.identity, official, austria.extras, measurement)


# FastF1 makes a session's laps from these four together, and none without any one of them.
NO_LAPS_WITHOUT = {"timing_data", "tyre_data", "track_status", "session_status"}


@pytest.mark.parametrize("bar", sorted(set(FEED_FILES) - NO_LAPS_WITHOUT))
def test_a_session_without_one_of_its_feeds_is_still_built_and_says_what_it_lacks(austria, generation, tmp_path, bar):
    """After its retry window a session short of a feed is published as it
    is. Measuring it is not enough to know that it can be: with F1's driver
    list gone the measurement was right and the build failed, because every
    lap FastF1 loads then has an empty driver code."""
    files = build_without(austria, tmp_path, bar)

    for path, data in files.items():
        model_for_artifact(path).model_validate_json(data)
    coverage = read(files, "coverage.json")
    assert coverage["complete"] is False and bar in {item["bar"] for item in coverage["shortfalls"]}
    # Everyone is there under the code the whole race gives them, with their laps.
    assert sorted(row["code"] for row in read(files, "drivers.json")) == sorted(
        row["code"] for row in read(generation.files, "drivers.json")
    )
    whole = {(row["driver_code"], row["lap_number"]) for row in read(generation.files, "laps.json")}
    laps = {(row["driver_code"], row["lap_number"]) for row in read(files, "laps.json")}
    # Without the lap count FastF1 drops the one lap it added for a retirement.
    assert laps == whole or (bar == "lap_count" and laps < whole and len(whole - laps) == 1)
    assert read(files, "results.json") == read(generation.files, "results.json")
    FEED_TABLE.append((FEED_FILES[bar], "session", f"built: {len(files)} files"))


@pytest.mark.parametrize("bar", sorted(NO_LAPS_WITHOUT))
def test_a_session_fastf1_can_make_no_laps_of_is_not_built_and_says_why(austria, tmp_path, bar):
    with pytest.raises(normalize.SessionDataError, match="The session has no laps"):
        build_without(austria, tmp_path, bar)


def test_a_driver_f1s_list_leaves_out_is_built_under_the_classifications_code(austria, generation, tmp_path):
    number, code = ONE_DRIVER

    files = build_without(austria, tmp_path, "driver_list", driver_number=number)

    # FastF1 loads no laps and no telemetry for a car that is not in the list.
    assert code in {row["code"] for row in read(files, "drivers.json")}
    assert f"telemetry/{code}.json" not in files
    assert read(files, "results.json") == read(generation.files, "results.json")
    assert (code, "driver_list") in {(item["driver"], item["bar"]) for item in read(files, "coverage.json")["shortfalls"]}


def test_a_driver_f1s_list_gives_no_code_is_built_under_the_classifications(austria, generation, tmp_path):
    """The form the twelfth review found: the list has the driver, with a
    number and names, and no three-letter code or broadcast name. FastF1
    writes the word ``None`` on every one of their laps."""
    number, code = ONE_DRIVER

    def no_code(feeds):
        path = feeds / FEED_FILES["driver_list"]
        with path.open("rb") as handle:
            cached = pickle.load(handle)
        entry = {key: value for key, value in cached["data"][number].items() if key not in ("Tla", "BroadcastName")}
        cached["data"] = {**cached["data"], number: entry}
        # A new file: the one there may share its bytes with the fixture's.
        path.unlink()
        with path.open("wb") as handle:
            pickle.dump(cached, handle)

    probe = without(austria.base, austria.snapshot, tmp_path / "probe", "lap_count")
    no_code(probe / austria.snapshot.identity.archive_path)
    loaded = load_offline(austria.snapshot, probe)
    assert set(loaded.laps.loc[loaded.laps["DriverNumber"] == number, "Driver"]) <= {"None", "nan"}

    files = build_without(austria, tmp_path, "lap_count", damage=no_code)

    assert "telemetry/NONE.json" not in files and "telemetry/NAN.json" not in files
    assert sorted(row["code"] for row in read(files, "drivers.json")) == sorted(
        row["code"] for row in read(generation.files, "drivers.json")
    )
    assert read(files, f"telemetry/{code}.json") == read(generation.files, f"telemetry/{code}.json")
    assert (code, "driver_list") in {(item["driver"], item["bar"]) for item in read(files, "coverage.json")["shortfalls"]}


@pytest.mark.parametrize("extra", [PIT_STOP_SERIES, CIRCUIT_INFO])
def test_a_session_without_one_of_the_extras_is_incomplete(austria, extra):
    extras = {name: data for name, data in austria.extras.items() if name != extra}
    measurement = apply_classification(measure_coverage(austria.session, "R", extras), classified_laps(austria.snapshot))

    found = [item.bar for item in evaluate_coverage(measurement)]

    FEED_TABLE.append((f"extra/{extra}", "session", f"incomplete: {', '.join(found)}"))
    assert found == [{PIT_STOP_SERIES: "pit_stop_series", CIRCUIT_INFO: "circuit_info"}[extra]]


def test_one_drivers_stops_missing_from_f1s_pit_stop_feed_is_the_removal_no_bar_notices(austria, generation):
    """The one case of rule 6 that holds neither way: the session stays
    complete and what is built changes. It cannot be made a bar, because F1's
    own feed leaves whole drivers out: three in this race as it was fetched,
    and between a quarter and all of the stops across the 2026 season. What a
    reader has instead is in the data: such a stop has ``stationary_ms`` null.
    Should a bar ever cover it, this test is the one to change."""
    number, code = ONE_DRIVER
    extras = without_pit_stops_of(austria.extras, number)
    session = load_offline(austria.snapshot, austria.base)
    official = recorded_classification(AUSTRIA)
    measurement = apply_classification(measure_coverage(session, "R", extras), official.laps_by_number)
    merge_into_session(session, official)

    files = build_artifacts(session, austria.snapshot.identity, official, extras, measurement)

    changed = sorted(path for path in files if files[path] != generation.files[path])
    FEED_TABLE.append((f"extra/{PIT_STOP_SERIES}", code, f"NEITHER: complete, and {', '.join(changed)} change"))
    assert evaluate_coverage(measurement) == []
    assert changed == ["coverage.json", "pit-stops.json"]
    stops = [stop for stop in read(files, "pit-stops.json") if stop["driver_code"] == code]
    assert len(stops) == 3 and all(stop["stationary_ms"] is None and stop["duration_ms"] for stop in stops)
    assert read(files, "coverage.json")["pit_stops_in_series"] == 33


# --- what F1's feeds have been seen to do --------------------------------------------


def recorded(tmp_path, session_key):
    """A session of the archive as a build loads it, with the feeds archived beside it."""
    snapshot, extras = restore(archive_store(), session_key, tmp_path / "cache")
    return load_offline(snapshot, tmp_path / "cache"), extras, snapshot


def test_the_rows_fastf1_adds_to_a_real_session_are_told_from_the_ones_f1_sent(tmp_path):
    """The 2026 Belgian GP: the car feed's first seven messages leave out
    most of the field, and FastF1 gives each car left out seven rows of
    zeros. A loaded session marks them with the text ``nan``, not with
    nothing, which is what the first fix looked for."""
    session, _, _ = recorded(tmp_path, BELGIUM)

    added = {number: ~sent_by_f1(frame) for number, frame in session.car_data.items()}

    assert {int(rows.sum()) for rows in added.values()} <= {0, 7} and sum(rows.any() for rows in added.values()) == 20
    for number, rows in added.items():
        frame = session.car_data[number]
        assert not frame.loc[rows, ["Speed", "RPM", "Throttle", "nGear"]].to_numpy().any()
        assert (frame.loc[~rows, "Source"] == "car").all()
    assert all(sent_by_f1(frame).all() for frame in session.pos_data.values())


def test_stops_f1_reported_late_and_with_no_lap_are_each_beside_the_stop_they_were_of(tmp_path):
    """The 2026 Australian GP: twenty of the pit-stop feed's twenty-eight
    reports name no lap. They were dropped, and the race was published with a
    stationary time for eight of its stops."""
    session, extras, _ = recorded(tmp_path, AUSTRALIA)

    reports = parse_pit_stop_series(extras[PIT_STOP_SERIES])
    stops = normalize.pit_stops(session, extras, normalize.driver_codes(session))

    vouched = [stop for stop in stops if stop.stationary_ms is not None]
    assert (len(reports), sum(1 for report in reports if report["lap_number"] is None)) == (28, 20)
    assert len(vouched) == 28
    # F1's own pit-lane time is the timing's to within a second for every
    # one of them: no report has been put beside another car's stop.
    assert all(
        stop.duration_ms is not None and abs(stop.pit_lane_ms - stop.duration_ms) < 1000 for stop in vouched
    )


def test_a_lap_whose_car_data_stops_short_is_not_published_and_was_never_counted(tmp_path):
    """The 2025 São Paulo sprint: Bortoleto crashed on the last lap, and his
    car's data stops 6.7 seconds before the lap is timed as ending."""
    session, extras, snapshot = recorded(tmp_path, SAO_PAULO_SPRINT_2025)

    telemetry = extract_telemetry(session)
    measured = measure_coverage(session, "S", extras)

    assert ("BOR", 24) not in telemetry.laps and ("BOR", 23) in telemetry.laps
    assert measured["drivers"]["BOR"]["car_laps"] == snapshot.coverage["drivers"]["BOR"]["car_laps"] == 23
    # Every lap the coverage counts is published. A lap FastF1 added for a car
    # that stopped on track is published too, and is not one the bar counts.
    for code, driver in measured["drivers"].items():
        published = len(telemetry.of_driver(code))
        assert driver["car_laps"] <= published <= driver["car_laps"] + driver["generated_laps"], code


def test_stops_f1_sends_twice_are_counted_once(tmp_path):
    """The 2025 Canadian GP: 29 of its stops arrive under two places of their
    driver's list, a tenth of a second apart. The count of stops the feed
    vouches for was 62, published beside 33 stops."""
    session, extras, snapshot = recorded(tmp_path, CANADA_2025)

    stops = normalize.pit_stops(session, extras, normalize.driver_codes(session))
    measured = measure_coverage(session, "R", extras)

    assert len(extras[PIT_STOP_SERIES].splitlines()) == 62
    assert measured["pit_stops_in_series"] == sum(1 for stop in stops if stop.stationary_ms is not None) == 33
    assert all(stop.duration_ms is None or abs(stop.pit_lane_ms - stop.duration_ms) < 1000 for stop in stops if stop.pit_lane_ms)


def test_the_zero_f1_sends_for_a_sensor_with_no_reading_is_not_a_track_temperature(tmp_path):
    """The 2026 Azerbaijan GP: two samples of 168 give the track as 0.0
    degrees, between 46.6 and 47.3 and between 39.8 and 40.1."""
    session, extras, _ = recorded(tmp_path, AZERBAIJAN)
    assert sorted(session.weather_data["TrackTemp"])[:3] == [0.0, 0.0, 38.7]

    samples = normalize.weather(session, "R", extras)

    track = [sample.track_temp_c for sample in samples]
    assert len(track) == 168 and track.count(None) == 2 and min(value for value in track if value is not None) == 38.7
    assert all(sample.air_temp_c is not None and sample.humidity_pct is not None for sample in samples)


# --- a race whose feeds repeat themselves --------------------------------------------


def test_the_hungarian_races_corners_are_placed_on_a_lap_whose_position_data_is_whole(tmp_path):
    """From lap 15 of the 2026 Hungarian race F1's position feed repeats nine
    samples in ten, for every car. The fastest lap is one of those, with a
    hole of 347 m in it: FastF1 placed the corners along it and put two pairs
    of them at one point, and measured against it they look up to 116 m off
    the track. The build takes the fastest lap whose position data is whole,
    and places them along that."""
    store = archive_store()
    snapshot, extras = restore(store, HUNGARY, tmp_path / "cache")
    archived = [corner["distance_m"] for corner in json.loads(extras[CIRCUIT_INFO])["corners"]]
    assert archived != sorted(set(archived))

    files = build_offline(store, snapshot, None)

    circuit = read(files, "corners.json")
    assert circuit["reference_lap"]["lap_number"] < 15
    assert 4_250 < circuit["reference_lap"]["length_m"] < 4_450
    assert (circuit["fits_track"], circuit["distance_source"]) == (True, "telemetry")
    assert circuit["off_track_m"] < 20
    distances = [corner["distance_m"] for corner in circuit["corners"]]
    assert len(distances) == 16 and distances == sorted(set(distances))
    assert read(files, "analysis/corner-analysis.json")["corner_source"] == "official"


# --- a race F1 holds only part of ------------------------------------------------


@pytest.fixture(scope="module")
def monaco(tmp_path_factory):
    base = tmp_path_factory.mktemp("monaco") / "cache"
    store = archive_store()
    snapshot, extras = restore(store, MONACO, base)
    recorded = SimpleNamespace(store=store, snapshot=snapshot, extras=extras, base=base)
    return SimpleNamespace(files=build(recorded, None), snapshot=snapshot, extras=extras, base=base)


def test_the_monaco_race_is_built_with_its_position_data_missing(monaco):
    """F1's position feed for the 2026 Monaco race stops in lap 5 of 78."""
    files = monaco.files
    index = read(files, "telemetry/index.json")
    laps = [lap for entry in index["drivers"] for lap in index_laps(entry)]

    assert len(files) == 43 and len(laps) == 1452
    assert {lap["lap_number"] for lap in laps if lap["has_position"]} == {1, 2, 3, 4, 5}
    assert sum(lap["has_position"] for lap in laps) < 90
    coverage = read(files, "coverage.json")
    assert sum(item["bar"] == "position" for item in coverage["shortfalls"]) == 21
    assert next(d for d in coverage["drivers"] if d["driver_code"] == "HAM")["position_laps"] in (4, 5)


def test_the_monaco_replay_stops_where_the_position_feed_does(monaco):
    replay = read(monaco.files, "position-replay.json")
    laps = read(monaco.files, "laps.json")

    # The feed stops at 3,710,541 ms on the session clock. No frame is later.
    assert replay["time_ms"] and replay["time_ms"][-1] <= 3_710_541
    # The lap the race had reached is the timing's to say, not the position
    # feed's: in every frame it is the highest lap any car had started by the
    # end of the frame's window. Every lap of this race has car data, so the
    # telemetry files say when each was started. The feed stops a few
    # seconds before the leader ends lap 5, and the sixth starts inside the
    # last frame.
    started: dict[int, int] = {}
    for path, data in monaco.files.items():
        if path.startswith("telemetry/") and path != "telemetry/index.json":
            for lap in json.loads(data)["laps"]:
                started[lap["lap_number"]] = min(started.get(lap["lap_number"], lap["start_ms"]), lap["start_ms"])
    for moment, reached in zip(replay["time_ms"], replay["lap_number"]):
        begun = [number for number, start in started.items() if start < moment + replay["interval_ms"]]
        assert reached == (max(begun) if begun else None), moment
    assert replay["lap_number"][-1] == 6 and replay["lap_number"].count(6) <= 2
    # Nothing is drawn at (0, 0), which F1 sends for a car it has no position for.
    for driver in replay["drivers"]:
        assert all(x != 0 or y != 0 for x, y in zip(driver["x"], driver["y"]) if x is not None)
    assert max(lap["lap_number"] for lap in laps) == 78


def test_the_monaco_analyses_that_need_position_say_so_and_the_rest_are_whole(monaco):
    files = monaco.files

    dominance = read(files, "analysis/track-dominance.json")
    assert dominance["minisector_count"] == 25 and len(dominance["representative_laps"]) == 21
    assert all(sector["midpoint"] == {"x": None, "y": None} for sector in dominance["minisectors"])
    assert any("no position data" in caveat for caveat in dominance["caveats"])
    assert read(files, "analysis/strategy.json")["pit_loss"]["stop_count"] == 89
    assert len(read(files, "analysis/car-performance.json")["drivers"]) == 22
    late = read(files, "telemetry/HAM.json")["laps"][40]
    # Car data alone is about 290 samples for a lap here, so nothing is thinned away.
    assert late["x"] is None and 250 < len(late["speed_kph"]) <= 300
    assert not np.isnan([value for lap in read(files, "telemetry/HAM.json")["laps"] for value in lap["distance_m"]]).any()


def test_the_monaco_corners_are_placed_by_the_build_on_a_lap_that_has_position_data(monaco):
    """FastF1 places a circuit's corners along the session's fastest lap. Here
    that lap has no position data, so the corners are archived without
    distances and the build places them, on the fastest of the few laps that
    have any. It is the one race of 2026 where the build has to."""
    if CIRCUIT_INFO not in monaco.extras:
        pytest.skip("this snapshot of the race was fetched before corners were archived without distances")
    circuit = read(monaco.files, "corners.json")
    analysis = read(monaco.files, "analysis/corner-analysis.json")

    assert (circuit["distance_source"], circuit["fits_track"]) == ("telemetry", True)
    assert circuit["off_track_m"] < 20 and circuit["reference_lap"]["lap_number"] <= 5
    assert 3_200 < circuit["reference_lap"]["length_m"] < 3_400
    distances = [corner["distance_m"] for corner in circuit["corners"]]
    assert len(distances) == 19 and distances == sorted(distances)
    # They are where the circuit's corners are: 21 cars take the hairpin at
    # about 45 kph and the tunnel flat, on laps that have no position data.
    assert analysis["corner_source"] == "official"
    apex = {
        corner["corner_number"]: sorted(row["apex_speed_kph"] for row in corner["drivers"])
        for corner in analysis["corners"]
    }
    slowest = min(apex, key=lambda number: apex[number][len(apex[number]) // 2])
    assert slowest == 6 and 40 <= apex[6][11] <= 50
    assert apex[9][11] > 240
    assert any("No position data on the lap of" in caveat for caveat in analysis["caveats"])


def test_a_lap_that_ends_at_the_chicane_has_no_figures_for_the_corners_after_it(monaco):
    """Verstappen's only lap of the race stops 2,107 m round. Tabac and the
    swimming pool are within 50 m of where he had been at the start of it."""
    if CIRCUIT_INFO not in monaco.extras:
        pytest.skip("this snapshot of the race was fetched before corners were archived without distances")
    analysis = read(monaco.files, "analysis/corner-analysis.json")

    assert {"driver_code": "VER", "lap_number": 1, "lap_time_ms": None} in analysis["representative_laps"]
    his = [
        corner["corner_number"]
        for corner in analysis["corners"]
        if any(row["driver_code"] == "VER" for row in corner["drivers"])
    ]
    assert his == list(range(1, 12))
    for corner in analysis["corners"]:
        assert len(corner["drivers"]) == (22 if corner["corner_number"] <= 11 else 21), corner["corner_number"]
    assert any("Not a whole timed lap: VER" in caveat for caveat in analysis["caveats"])


def test_monaco_without_its_circuit_file_has_its_corners_inferred(monaco):
    """As the race was first archived. No lap that is compared has position data."""
    extras = {name: data for name, data in monaco.extras.items() if name != CIRCUIT_INFO}
    session = load_offline(monaco.snapshot, monaco.base)
    measurement = measure_coverage(session, "R", extras)

    files = build_artifacts(session, monaco.snapshot.identity, None, extras, measurement)

    assert read(files, "corners.json")["corners"] == []
    assert "circuit_info" in {item["bar"] for item in read(files, "coverage.json")["shortfalls"]}
    analysis = read(files, "analysis/corner-analysis.json")
    assert analysis["corner_source"] == "inferred" and len(analysis["corners"]) >= 8
    assert any("no position data" in caveat for caveat in analysis["caveats"])
