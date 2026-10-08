"""The cases the twenty-ninth review of this code found (GPT-6.1 Sol, 2026-10-08, at cf96efa).

The round confirmed the reading of 104 as F1's mark for a pedal with no
reading, and that the raw car feed lines up with FastF1's table of it for
every car of the twelve sessions it checked. It found three things more.

- A gear that is no gear. In the 2026 Dutch GP car 1 sends a "gear" between
  9 and 40 for fourteen seconds in the pit lane, and Norris's lap 4 was
  published with twenty of them.
- A corner the brake has no reading for was published as a corner the driver
  did not brake for: Gasly into turn 9 on lap 56 of the 2026 Australian GP.
- The raw responses were loaded into a database in memory, which Python can
  do only where its SQLite was built to allow it.

The stand-in cases are in tests/test_carfeed.py and
backend/tests/test_corner_analysis.py; these are the two races, from the
archive.
"""

from __future__ import annotations

import json

from f1data.archive import read_raw_response
from f1data.artifacts import build_artifacts
from f1data.carfeed import CAR_FEED
from f1data.coverage import measure_coverage
from f1data.telemetry import extract_telemetry
from tests.recorded import archive_store
from tests.test_recorded_race import recorded

AUSTRALIA_2026 = 11234
DUTCH_2026 = 11353


def test_the_2026_dutch_gp_has_no_gear_that_no_car_has(tmp_path):
    session, _, _ = recorded(tmp_path, DUTCH_2026)

    telemetry = extract_telemetry(session)

    norris = telemetry.laps[("NOR", 4)]
    # As F1 sent it, and as it was published: up to 40.
    assert int(norris.gear.max()) == 40
    gears = norris.gears()
    assert None in gears and max(gear for gear in gears if gear is not None) <= 8
    # Everything else of those samples is there: the car standing, its engine running.
    unread = [index for index, gear in enumerate(gears) if gear is None]
    assert float(norris.speed_kph[unread].max()) == 0.0 and float(norris.rpm[unread].min()) > 0
    for lap in telemetry.laps.values():
        known = [gear for gear in lap.gears() if gear is not None]
        assert not known or (min(known) >= 0 and max(known) <= 8)


def test_gaslys_turn_nine_is_not_published_as_a_corner_he_did_not_brake_for(tmp_path):
    """Lap 56 of the 2026 Australian GP: no brake reading for the 365 m before the corner, from 311 km/h to 218."""
    session, found, snapshot = recorded(tmp_path, AUSTRALIA_2026)
    feed = read_raw_response(archive_store(), snapshot, CAR_FEED)

    files = build_artifacts(session, snapshot.identity, None, found, measure_coverage(session, "R", found), feed)
    result = json.loads(files["analysis/corner-analysis.json"])

    assert result["corner_source"] == "official"
    assert [row["lap_number"] for row in result["representative_laps"] if row["driver_code"] == "GAS"] == [56]
    turn_nine = next(corner for corner in result["corners"] if corner["corner_number"] == 9)
    gasly = next(row for row in turn_nine["drivers"] if row["driver_code"] == "GAS")
    assert gasly["brake_known"] is False and gasly["brake_start_m"] is None
    assert gasly["apex_speed_kph"] == 212.0
    # Nearly every row of the race has every reading, and says so.
    rows = [row for corner in result["corners"] for row in corner["drivers"]]
    assert sum(row["brake_known"] for row in rows) > len(rows) * 0.95
    assert "GAS" in result["caveats"][-1] and "no brake reading" in result["caveats"][-1]
