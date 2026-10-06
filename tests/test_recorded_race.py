"""The build, on recorded races from the source archive.

    F1DATA_TEST_ARCHIVE=<a directory store, or r2> python -m pytest tests/test_recorded_race.py -s

Skipped unless the variable is set. Nothing here touches the network: the
sessions are loaded from the archive with every host refused, and the Austrian
race's classification is a fixture (tests/recorded.py).

Three things are checked that only real data can check:

* The telemetry this build makes is FastF1's own, sample for sample.
* A golden build of the 2026 Austrian GP (session 11315): the figures a
  regression would move, and a checksum of every file
  (docs/architecture-review-findings.md, AR-08).
* Every feed has a coverage bar that notices it missing: each of the eleven
  FastF1 requests and both extras is removed in turn, for the session and
  where it applies for a single driver, and the session has to come out
  incomplete (section 6, rule 6). ``-s`` prints the table.

To record the golden file again after an intended change:

    F1DATA_WRITE_FIXTURES=1 F1DATA_TEST_ARCHIVE=... python -m pytest tests/test_recorded_race.py
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from types import SimpleNamespace

import numpy as np
import pytest

from backend.app.analysis.advanced import calculate_car_performance, calculate_track_dominance
from backend.app.analysis.position_replay import build_position_replay
from f1data import layout, normalize
from f1data.analyses import LapRows, position_replay, sample_rows
from f1data.artifacts import build_artifacts
from f1data.classification import merge_into_session
from f1data.coverage import apply_classification, evaluate_coverage, measure_coverage
from f1data.extras import CIRCUIT_INFO, PIT_STOP_SERIES
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
GOLDEN = FIXTURES / f"golden-{AUSTRIA}.json"
# The driver each single-driver removal is made for: Hamilton, who finished
# and stopped three times.
ONE_DRIVER = ("44", "HAM")
FEED_TABLE: list[tuple[str, str, str]] = []


@pytest.fixture(scope="module")
def austria(tmp_path_factory):
    base = tmp_path_factory.mktemp("austria") / "cache"
    snapshot, extras = restore(archive_store(), AUSTRIA, base)
    return SimpleNamespace(snapshot=snapshot, extras=extras, base=base, session=load_offline(snapshot, base))


@pytest.fixture(scope="module")
def telemetry(austria):
    return extract_telemetry(austria.session)


def build(recorded, official):
    """What ``Builder.build`` does once it has the session, the extras and the classification."""
    session = load_offline(recorded.snapshot, recorded.base)
    if official is not None:
        merge_into_session(session, official)
    measurement = measure_coverage(session, recorded.snapshot.identity.session_type, recorded.extras)
    return build_artifacts(session, recorded.snapshot.identity, official, recorded.extras, measurement)


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
    assert read(files, "corners.json")["distance_source"] == "archive"
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
    assert len(files["telemetry/index.json"]) < 60_000
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
    files = build(austria, None)

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
    merge_into_session(session, official)
    measurement = measure_coverage(session, "R", extras)

    files = build_artifacts(session, austria.snapshot.identity, official, extras, measurement)

    changed = sorted(path for path in files if files[path] != generation.files[path])
    FEED_TABLE.append((f"extra/{PIT_STOP_SERIES}", code, f"NEITHER: complete, and {', '.join(changed)} change"))
    assert evaluate_coverage(measurement) == []
    assert changed == ["coverage.json", "pit-stops.json"]
    stops = [stop for stop in read(files, "pit-stops.json") if stop["driver_code"] == code]
    assert len(stops) == 3 and all(stop["stationary_ms"] is None and stop["duration_ms"] for stop in stops)
    assert read(files, "coverage.json")["pit_stops_in_series"] == 33


# --- a race F1 holds only part of ------------------------------------------------


@pytest.fixture(scope="module")
def monaco(tmp_path_factory):
    base = tmp_path_factory.mktemp("monaco") / "cache"
    snapshot, extras = restore(archive_store(), MONACO, base)
    recorded = SimpleNamespace(snapshot=snapshot, extras=extras, base=base)
    return SimpleNamespace(files=build(recorded, None), snapshot=snapshot)


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

    assert replay["time_ms"] and max(number for number in replay["lap_number"] if number) == 5
    # The feed stops at 3,710,541 ms on the session clock. No frame is later.
    assert replay["time_ms"][-1] <= 3_710_541
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
    corners = read(files, "analysis/corner-analysis.json")
    assert corners["corner_source"] == "inferred" and len(corners["corners"]) >= 8
    assert any("no position data" in caveat for caveat in corners["caveats"])
    assert read(files, "analysis/strategy.json")["pit_loss"]["stop_count"] == 89
    assert len(read(files, "analysis/car-performance.json")["drivers"]) == 22
    late = read(files, "telemetry/HAM.json")["laps"][40]
    # Car data alone is about 290 samples for a lap here, so nothing is thinned away.
    assert late["x"] is None and 250 < len(late["speed_kph"]) <= 300
    assert not np.isnan([value for lap in read(files, "telemetry/HAM.json")["laps"] for value in lap["distance_m"]]).any()
