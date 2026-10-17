"""The cases a Claude review of pull request 11 found in the analyses, 2026-10-17, at 5190b36.

Six findings and two smaller ones. All but the two smaller ones and the tyre
fit's split stint were found on real sessions, in the old pipeline's per-lap
data of the 2025 races and the first nine of 2026.

The car-performance profiles and the corner table took each driver's fastest
lap with any telemetry, as track dominance once did: a lap 1, or a lap that
stops where the car did, was profiled and averaged into its team's figures.
The tyre fit grouped laps by their own compound, so a stint whose compound F1
names late was two rows, and laps with no tyre data at all were a row of
"stint 0" said to be on a set that went on used. The ideal lap was made of
in-laps, out-laps and lap 1, and came out slower than the best lap. Race pace
ranked a median of one opening lap against medians of sixty. The team-mate
comparison left out, and said nothing of, a team with a driver who had no
clean lap. And the old pipeline, which still runs on main, lost its pit-lane
figures to a rule for stops it has no way to tell apart.

Also: inferred corners merged two brakings the car was driven on between, and
the fuel correction read a session's name before its code.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.analysis.advanced import (
    DEFAULT_RACE_FUEL_CORRECTION_MS_PER_LAP,
    DEFAULT_SPRINT_FUEL_CORRECTION_MS_PER_LAP,
    calculate_car_performance,
    calculate_corner_analysis,
    calculate_fuel_adjusted_tyre_degradation,
)
from app.analysis.ideal_laps import calculate_ideal_laps
from app.analysis.race_pace import calculate_race_pace
from app.analysis.strategy import calculate_strategy
from app.analysis.teammate_comparison import calculate_teammate_comparison

LAP_LENGTH_M = 4_000
BRAKED = (1_000, 3_000)
CORNERS = [
    {"number": 1, "letter": "", "x": 10_000.0, "y": 0.0, "distance_m": 1_000.0},
    {"number": 2, "letter": "", "x": 20_000.0, "y": 0.0, "distance_m": 2_000.0},
    {"number": 3, "letter": "", "x": 30_000.0, "y": 0.0, "distance_m": 3_000.0},
]


def lap(driver, number, lap_time_ms, **fields):
    """A lap as laps.json has it: clean unless ``fields`` say otherwise."""
    return {
        "driver_code": driver,
        "lap_number": number,
        "lap_time_ms": lap_time_ms,
        "sector_1_ms": None,
        "sector_2_ms": None,
        "sector_3_ms": None,
        "compound": "MEDIUM",
        "tyre_age": number,
        "stint": 1,
        "is_pit_in_lap": False,
        "is_pit_out_lap": False,
        "is_deleted": False,
        "is_accurate": True,
        "track_status": "1",
        **fields,
    }


def telemetry(driver, number, *, top_kph=300.0, standing_start=False, stops_at=LAP_LENGTH_M):
    """A lap along a straight line sampled every ten metres, and how long it takes.

    The car brakes from ``top_kph`` to 90 km/h for corners 1 and 3, and on a
    standing start gathers speed from 40 km/h over the first 400 m. It stops
    ``stops_at`` metres round.
    """
    rows, elapsed = [], 0.0
    for step in range(stops_at // 10 + 1):
        place = step * 10.0
        speed, braking = top_kph, False
        for corner in BRAKED:
            if corner - 150 <= place <= corner:
                speed, braking = top_kph - (top_kph - 90.0) * (place - (corner - 150)) / 150, True
            elif corner < place <= corner + 200:
                speed = 90.0 + (top_kph - 90.0) * (place - corner) / 200
        if standing_start and place < 400:
            speed = min(speed, 40.0 + (top_kph - 40.0) * place / 400)
        if step:
            elapsed += 10.0 / (speed / 3.6) * 1000
        rows.append(
            {
                "driver_code": driver,
                "lap_number": number,
                "distance_m": place,
                "relative_time_ms": elapsed,
                "speed_kph": speed,
                "brake": braking,
                "throttle_pct": 0 if braking else 100,
                "x": place * 10,
                "y": 0.0,
            }
        )
    return rows, round(elapsed)


def team(code, name):
    return {"code": code, "team": {"name": name}}


def out_early_session():
    """Two teams with a driver out early, as in the 2026 Monaco and Austrian GPs.

    Verstappen's only lap of Monaco is lap 1, which has no lap time and stops
    at the chicane, 2,107 m round. Bottas ran lap 1 of Austria (84.016 s) and
    an in-lap. Their team-mates and two others have a lap 5 each.
    """
    laps, rows = [], []
    for driver, top in (("HAD", 300.0), ("PER", 296.0), ("RUS", 304.0), ("ANT", 302.0)):
        samples, took = telemetry(driver, 5, top_kph=top)
        laps.append(lap(driver, 5, took))
        rows += samples
    first, _ = telemetry("VER", 1, standing_start=True, stops_at=2_100)
    laps.append(lap("VER", 1, None, is_accurate=False))
    rows += first
    first, took = telemetry("BOT", 1, top_kph=320.0, standing_start=True)
    in_lap, slower = telemetry("BOT", 2, top_kph=280.0)
    laps += [lap("BOT", 1, took, is_accurate=False), lap("BOT", 2, slower, is_pit_in_lap=True)]
    rows += first + in_lap
    drivers = [
        team("HAD", "Red Bull Racing"),
        team("VER", "Red Bull Racing"),
        team("BOT", "Cadillac"),
        team("PER", "Cadillac"),
        team("RUS", "Mercedes"),
        team("ANT", "Mercedes"),
    ]
    return laps, rows, drivers


class OutEarlyLapTests(unittest.TestCase):
    """Finding 1: a lap 1 or a lap that stops short was profiled, and in its team's figures."""

    def test_a_driver_with_no_whole_clean_lap_is_not_profiled_nor_in_the_teams_figures(self):
        laps, rows, drivers = out_early_session()

        result = calculate_car_performance("s", laps, rows, drivers)
        profiles = {row["driver_code"]: row for row in result["drivers"]}
        teams = {row["team"]: row for row in result["teams"]}

        self.assertEqual(set(profiles), {"HAD", "PER", "RUS", "ANT"})
        # Verstappen's lap 1 went no faster than 300 km/h and was mostly a
        # start: averaged in, it took Red Bull's figures down with it.
        self.assertEqual(teams["Red Bull Racing"]["drivers"], ["HAD"])
        for field in ("max_speed_kph", "high_speed_avg_kph", "full_throttle_pct", "braking_pct"):
            self.assertEqual(teams["Red Bull Racing"][field], profiles["HAD"][field], field)
            self.assertEqual(teams["Cadillac"][field], profiles["PER"][field], field)
        self.assertEqual(teams["Mercedes"]["drivers"], ["ANT", "RUS"])
        self.assertIn(
            "Profiles use each driver's fastest clean lap with complete telemetry: accurate, not deleted, "
            "not a pit lap, not lap 1 and not run under a safety car, VSC or red flag.",
            result["caveats"],
        )
        self.assertIn("Left out, having no such lap, and so not in their team's figures: BOT, VER.", result["caveats"])
        self.assertNotIn("Profiles use each driver's fastest non-deleted lap with telemetry.", result["caveats"])

    def test_the_corner_table_leaves_them_out_and_says_so(self):
        laps, rows, _ = out_early_session()

        for corners in (CORNERS, None):
            with self.subTest(official=corners is not None):
                result = calculate_corner_analysis("s", laps, rows, corners, reference_lap_length_m=LAP_LENGTH_M)

                self.assertEqual(
                    [(row["driver_code"], row["lap_number"]) for row in result["representative_laps"]],
                    [("ANT", 5), ("HAD", 5), ("PER", 5), ("RUS", 5)],
                )
                for corner in result["corners"]:
                    self.assertEqual({row["driver_code"] for row in corner["drivers"]}, {"ANT", "HAD", "PER", "RUS"})
                self.assertIn("Left out, having no such lap: BOT, VER.", result["caveats"])
                self.assertIn(
                    "Each driver's fastest clean lap whose telemetry runs the length of its lap time is compared: "
                    "accurate, not deleted, not a pit lap, not lap 1 and not run under a safety car, VSC or red flag.",
                    result["caveats"],
                )
                self.assertFalse(any("Not a whole timed lap" in caveat for caveat in result["caveats"]))

    def test_a_driver_with_a_whole_clean_lap_slower_than_their_first_is_compared_on_it(self):
        """A lap 1 or an in-lap is never the one compared, however quick."""
        laps, rows, drivers = out_early_session()
        later, took = telemetry("BOT", 3, top_kph=290.0)
        laps.append(lap("BOT", 3, took))

        corners = calculate_corner_analysis("s", laps, rows + later, CORNERS)
        profiles = calculate_car_performance("s", laps, rows + later, drivers)

        self.assertIn(("BOT", 3), [(row["driver_code"], row["lap_number"]) for row in corners["representative_laps"]])
        self.assertEqual(next(row for row in profiles["drivers"] if row["driver_code"] == "BOT")["lap_number"], 3)
        self.assertIn("Left out, having no such lap: VER.", corners["caveats"])


def tyre_laps(driver, numbers, *, stint, compound="MEDIUM", first_age=1, lap_time=None):
    """Clean laps on one set from ``first_age``, slowing 60 ms a lap of age and quickening 55 ms a lap of fuel."""
    rows = []
    for offset, number in enumerate(numbers):
        age = first_age + offset
        rows.append(
            lap(
                driver,
                number,
                lap_time(number) if lap_time else 90_000 + 60 * age - 55 * number,
                compound=compound,
                tyre_age=age,
                stint=stint,
            )
        )
    return rows


class TyreStintTests(unittest.TestCase):
    """Finding 2: rows for laps with no tyre data, and a stint split by when F1 names its compound."""

    def test_laps_with_no_tyre_data_are_in_no_row_and_the_result_says_why(self):
        """The 2025 Miami GP: F1's tyre data begins on lap 25, and 15 drivers each had a row of
        "stint 0", compound null, said to be short of tyre ages because F1 gives none for a set
        that went on used."""
        laps = [lap("VER", number, 92_000, compound=None, tyre_age=None, stint=None) for number in range(1, 25)]
        laps += tyre_laps("VER", range(25, 45), stint=1)

        result = calculate_fuel_adjusted_tyre_degradation("s", {"session": "Race", "type": "R"}, laps)

        self.assertEqual([(row["stint"], row["compound"]) for row in result["rows"]], [(1, "MEDIUM")])
        self.assertIn(
            "F1's tyre data gives no stint for 23 clean laps, of VER, so the set they were run on is not "
            "known and they are in no row. It gives no compound or tyre age for them either.",
            result["caveats"],
        )
        every = " ".join(result["caveats"] + [caveat for row in result["rows"] for caveat in row["caveats"]])
        self.assertNotIn("went on used", every)

    def test_a_stint_whose_compound_is_named_late_is_one_row(self):
        """F1 often names a set's compound some laps after it went on (f1data.normalize.stints)."""
        for named_from in (27, 31, 34):
            for unnamed in (None, "nan"):
                with self.subTest(named_from=named_from, unnamed=unnamed):
                    laps = tyre_laps("VER", range(2, 19), stint=1, compound="SOFT", first_age=2)
                    laps.append(lap("VER", 19, 110_000, compound="SOFT", tyre_age=19, is_pit_in_lap=True))
                    laps.append(lap("VER", 20, 110_000, compound=None, tyre_age=1, stint=2, is_pit_out_lap=True))
                    for row in tyre_laps("VER", range(21, 41), stint=2, first_age=2):
                        row["compound"] = "MEDIUM" if row["lap_number"] >= named_from else unnamed
                        laps.append(row)

                    result = calculate_fuel_adjusted_tyre_degradation("s", {"type": "R"}, laps)
                    second = [row for row in result["rows"] if row["stint"] == 2]

                    self.assertEqual(len(second), 1)
                    self.assertEqual(
                        (second[0]["compound"], second[0]["sample_count"], second[0]["stint_length"]),
                        ("MEDIUM", 20, 20),
                    )
                    self.assertEqual(second[0]["fit_status"], "ok")
                    self.assertEqual(second[0]["degradation_ms_per_lap"], 60.0)

    def test_a_change_of_compound_under_one_number_is_two_rows_as_in_stints_json(self):
        """F1 correcting itself: the run before the change and the run after are two stints."""
        laps = tyre_laps("VER", range(2, 12), stint=1, compound="SOFT", first_age=2)
        laps += tyre_laps("VER", range(12, 22), stint=1, compound="MEDIUM", first_age=12)

        result = calculate_fuel_adjusted_tyre_degradation("s", {"type": "R"}, laps)

        self.assertEqual([(row["stint"], row["compound"]) for row in result["rows"]], [(1, "SOFT"), (1, "MEDIUM")])

    def test_a_stint_with_no_tyre_ages_is_not_said_to_be_on_a_used_set(self):
        """F1 gives ages for sets that went on used: of the 2025 Spanish GP's later stints, 21 begin
        on a used set with an age."""
        laps = tyre_laps("BEA", range(41, 60), stint=3, compound="SOFT")
        for row in laps:
            row["tyre_age"] = None

        (row,) = calculate_fuel_adjusted_tyre_degradation("s", {"type": "R"}, laps)["rows"]

        self.assertEqual(
            row["caveats"],
            [
                "No rate reported: F1's tyre data gives a tyre age for 0 of the stint's 19 clean laps, and "
                "at least 8 with one are required."
            ],
        )


class IdealLapTests(unittest.TestCase):
    """Finding 3: an ideal lap slower than the best lap."""

    def test_an_ideal_lap_is_of_clean_laps_and_never_slower_than_the_best(self):
        """Bortoleto in the 2025 Las Vegas GP: lap 1 and an in-lap, then out. His ideal lap of
        2:23.044 was 12.618 s slower than his lap 1."""
        laps = [
            lap("BOR", 1, 130_426, sector_2_ms=38_734, sector_3_ms=44_553, is_pit_in_lap=True,
                is_accurate=False, track_status="12"),
            lap("BOR", 2, None, sector_1_ms=59_757, sector_2_ms=45_862, sector_3_ms=56_007,
                is_pit_in_lap=True, is_pit_out_lap=True, is_accurate=False, track_status="26"),
        ]
        laps += [
            lap("NOR", number, 94_000 + time, sector_1_ms=30_000 + time, sector_2_ms=34_000, sector_3_ms=30_000)
            for number, time in ((2, 300), (3, 0), (4, 200))
        ]
        # Lap 1 has the quickest last two sectors, from the line.
        laps.append(lap("NOR", 1, 99_000, sector_2_ms=33_000, sector_3_ms=29_000, is_accurate=False))

        rows = {row["driver_code"]: row for row in calculate_ideal_laps("s", laps)["rows"]}

        self.assertEqual(
            rows["BOR"],
            {
                "driver_code": "BOR",
                "best_sector_1_ms": None,
                "best_sector_2_ms": None,
                "best_sector_3_ms": None,
                "ideal_lap_ms": None,
                "best_lap_ms": None,
                "delta_to_ideal_ms": None,
            },
        )
        self.assertEqual((rows["NOR"]["ideal_lap_ms"], rows["NOR"]["best_lap_ms"]), (94_000, 94_000))
        self.assertEqual(rows["NOR"]["delta_to_ideal_ms"], 0)

    def test_no_time_left_is_given_where_the_ideal_is_slower_than_the_best_lap(self):
        """F1 can time a lap and leave a sector out."""
        laps = [
            lap("NOR", 2, 94_000, sector_1_ms=30_000, sector_2_ms=None, sector_3_ms=30_000),
            lap("NOR", 3, 95_000, sector_1_ms=30_400, sector_2_ms=34_500, sector_3_ms=30_100),
        ]

        (row,) = calculate_ideal_laps("s", laps)["rows"]

        self.assertEqual((row["ideal_lap_ms"], row["best_lap_ms"], row["delta_to_ideal_ms"]), (94_500, 94_000, None))


class RacePaceTests(unittest.TestCase):
    """Finding 4: a median of an opening lap or two ranked against medians of the whole race."""

    @staticmethod
    def race():
        laps = []
        for driver, pace in (("VER", 80_000), ("NOR", 80_400), ("PIA", 80_600)):
            laps += [lap(driver, number, pace) for number in range(1, 62)]
        # Out after half the clean laps, which is the least that is ranked.
        laps += [lap("ALO", number, 81_000) for number in range(1, 32)]
        # Out on lap 25, and on lap 5 with one clean lap, on heavier fuel.
        laps += [lap("HUL", number, 81_500) for number in range(1, 25)]
        laps += [lap("LAW", 1, 90_000), lap("LAW", 2, 83_022), lap("LAW", 3, 99_000, is_pit_in_lap=True)]
        # Three quick laps on new tyres and an empty tank are no pace either.
        laps += [lap("STR", number, 79_000) for number in range(58, 61)]
        return laps

    def test_a_driver_with_too_few_clean_laps_has_no_gap_and_does_not_set_the_best(self):
        """The 2025 Mexico City GP: Lawson, out after five laps, ranked 3.02 s off on one clean lap."""
        result = calculate_race_pace("s", self.race())
        rows = {row["driver_code"]: row for row in result["drivers"]}

        self.assertEqual(
            [(row["driver_code"], row["gap_to_best_ms"]) for row in result["drivers"]],
            [("VER", 0), ("NOR", 400), ("PIA", 600), ("ALO", 1_000), ("HUL", None), ("LAW", None), ("STR", None)],
        )
        # Their figures are still there, with what they are over.
        self.assertEqual((rows["LAW"]["lap_count"], rows["LAW"]["median_lap_ms"]), (1, 83_022))
        self.assertEqual(rows["ALO"]["lap_count"], 30)
        self.assertIn(
            "A driver has a gap to the best only with at least half as many clean laps as the driver with the "
            "most, who has 60, and at least 5. No gap for HUL (23), LAW (1), STR (3).",
            result["caveats"],
        )

    def test_a_stint_of_fewer_than_five_clean_laps_has_no_gap(self):
        laps = [lap("VER", number, 80_000, stint=1) for number in range(1, 30)]
        laps += [lap("VER", number, 79_000, stint=2) for number in range(30, 34)]

        result = calculate_race_pace("s", laps)

        self.assertEqual([(row["stint"], row["gap_to_best_ms"]) for row in result["stints"]], [(1, 0), (2, None)])
        self.assertIn("A stint has a gap to the best stint only with at least 5 clean laps.", result["caveats"])

    def test_race_pace_has_no_stint_row_for_laps_with_no_stint(self):
        """Finding 2: such a row had a stint of null, which is how the row for the whole race is marked."""
        laps = [lap("VER", number, 92_000, compound=None, tyre_age=None, stint=None) for number in range(1, 25)]
        laps += tyre_laps("VER", range(25, 45), stint=1)

        result = calculate_race_pace("s", laps)

        self.assertEqual([row["stint"] for row in result["stints"]], [1])
        self.assertEqual([row["lap_count"] for row in result["drivers"]], [43])
        self.assertIn(
            "F1's tyre data gives no stint for 23 clean laps, of VER. They are in the drivers' rows and in no "
            "stint's.",
            result["caveats"],
        )


class TeammateRowTests(unittest.TestCase):
    """Finding 5: a team left out, and nothing said, when a driver had no clean lap."""

    def test_a_team_with_a_driver_who_has_no_clean_lap_has_a_row_with_no_figures(self):
        """The 2025 Austrian GP lost Mercedes, Red Bull and Williams: Antonelli and Verstappen were
        out on lap 1, Albon retired after 15 laps, and Sainz did not start."""
        laps = []
        for driver in ("NOR", "PIA", "RUS", "TSU"):
            laps += [lap(driver, number, 70_000) for number in range(1, 30)]
        laps += [lap("ANT", 1, None), lap("VER", 1, None)]
        laps += [lap("ALB", number, 70_500) for number in range(1, 11)]
        drivers = [
            team("NOR", "McLaren"), team("PIA", "McLaren"),
            team("RUS", "Mercedes"), team("ANT", "Mercedes"),
            team("TSU", "Red Bull Racing"), team("VER", "Red Bull Racing"),
            team("ALB", "Williams"), team("SAI", "Williams"),
        ]

        result = calculate_teammate_comparison("s", laps, drivers)
        rows = {row["team"]: row for row in result["rows"]}

        self.assertEqual(set(rows), {"McLaren", "Mercedes", "Red Bull Racing", "Williams"})
        self.assertIsNone(rows["McLaren"].get("caveat"))
        self.assertEqual(rows["Mercedes"]["caveat"], "No gap: ANT's one lap is not a clean lap.")
        self.assertEqual(rows["Red Bull Racing"]["caveat"], "No gap: VER's one lap is not a clean lap.")
        self.assertEqual(rows["Williams"]["caveat"], "No gap: SAI ran no lap.")
        self.assertEqual(
            rows["Williams"]["drivers"],
            [
                {"driver_code": "ALB", "average_lap_ms": None, "lap_count": 0, "clean_lap_count": 9},
                {"driver_code": "SAI", "average_lap_ms": None, "lap_count": 0, "clean_lap_count": 0},
            ],
        )
        for name in ("Mercedes", "Red Bull Racing", "Williams"):
            row = rows[name]
            self.assertEqual(
                (row["gap_ms"], row["gap_spread_ms"], row["matched_lap_count"], row["trimmed_lap_count"]),
                (None, None, 0, 0),
            )
        self.assertNotIn("No team had two drivers with clean laps.", result["caveats"])

    def test_a_team_with_one_driver_or_none_who_ran_is_named(self):
        """Stroll did not start the 2025 Spanish GP and is not in its driver list."""
        laps = [lap(driver, number, 70_000) for driver in ("NOR", "PIA", "ALO") for number in range(1, 20)]
        drivers = [
            team("NOR", "McLaren"), team("PIA", "McLaren"),
            team("ALO", "Aston Martin"),
            team("GAS", "Alpine"), team("COL", "Alpine"),
        ]

        result = calculate_teammate_comparison("s", laps, drivers)

        self.assertEqual([row["team"] for row in result["rows"]], ["McLaren"])
        self.assertIn("No row for Aston Martin: the session has one driver of the team.", result["caveats"])
        self.assertIn("No row for Alpine: neither driver ran a lap for the team.", result["caveats"])


if __name__ == "__main__":
    unittest.main()
