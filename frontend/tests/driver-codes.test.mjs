import assert from "node:assert/strict";
import test from "node:test";

import { groupByDriver, seriesToRows } from "../src/lib/chart-utils.ts";
import { driverStyle, FALLBACK_DRIVER_COLOR, teamColorByDriver, teamDriverStyles } from "../src/lib/driver-style.ts";
import { fastestLapByDriver } from "../src/lib/lap-summary.ts";
import { minisectorTally } from "../src/lib/performance-view.ts";
import { compareTelemetry, defaultComparison, readTelemetry, telemetryLaps } from "../src/lib/published/telemetry.ts";
import { shareReads } from "../src/lib/published/share.ts";
import { resultPosition } from "../src/lib/results-view.ts";
import { driverCards, teamCards } from "../src/lib/session-summaries.ts";
import { pitStopLog } from "../src/lib/strategy-view.ts";
import { tyreAgePlot } from "../src/lib/tyre-chart.ts";

import { bucketOf, clientOf, generationPrefix, republish, SESSION_KEY } from "./support/published-bucket.mjs";

// A driver whom neither F1's driver list nor the classification names is
// published under the car number, as text: "44" where another driver has
// "HAM". It is the driver's code in every file, so it is a key, a label, a
// sort key and part of a file's path. None of them may assume three letters.
const NUMBERED = "44";

const lap = (driver, number, time) => ({
  driver_code: driver,
  lap_number: number,
  lap_time_ms: time,
  sector_1_ms: null,
  sector_2_ms: null,
  sector_3_ms: null,
  compound: "MEDIUM",
  tyre_age: number,
  stint: 1,
  position: null,
  is_pit_in_lap: false,
  is_pit_out_lap: false,
  is_deleted: false,
  is_accurate: true,
  track_status: "1"
});

const telemetryLap = (number, pace) => {
  const samples = [0, 1, 2, 3, 4];
  return {
    lap_number: number,
    start_ms: 3_500_000 + number * 80_000,
    time_ms: samples.map((index) => index * pace),
    distance_m: samples.map((index) => index * 1000),
    speed_kph: samples.map((index) => 200 + index * 20),
    throttle_pct: samples.map(() => 100),
    brake: samples.map(() => false),
    rpm: samples.map(() => 11000),
    gear: samples.map(() => 7),
    drs: null,
    x: null,
    y: null
  };
};

const indexEntry = (code, laps) => ({
  driver_code: code,
  path: `telemetry/${code}.json`,
  lap_number: laps.map((row) => row.lap_number),
  lap_time_ms: laps.map((row) => row.lap_time_ms),
  compound: laps.map((row) => row.compound),
  is_accurate: laps.map(() => true),
  is_deleted: laps.map(() => false),
  is_pit_in_lap: laps.map(() => false),
  is_pit_out_lap: laps.map(() => false),
  sample_count: laps.map(() => 5),
  raw_sample_count: laps.map(() => 5),
  has_position: laps.map(() => false)
});

const LAPS = [lap("RUS", 2, 70_500), lap(NUMBERED, 2, 70_300), lap(NUMBERED, 3, 70_900)];

/** A session in which car 44 has no name: its telemetry is under telemetry/44.json. */
async function sessionWithNumberedDriver() {
  const bucket = bucketOf();
  const drivers = [
    { code: "RUS", driver_id: "rus", full_name: "George Russell", number: 63, country: null, team: { team_id: "mercedes", name: "Mercedes", color: "#00D7B6" } },
    // What is known of a driver nobody names: the number, twice.
    { code: NUMBERED, driver_id: NUMBERED, full_name: NUMBERED, number: 44, country: null, team: null }
  ];
  const generation = republish(bucket, {
    "drivers.json": drivers,
    "telemetry/index.json": {
      channels: ["time_ms", "distance_m", "speed_kph", "throttle_pct", "brake", "rpm", "gear"],
      max_samples_per_lap: 300,
      drivers: ["RUS", NUMBERED].map((code) => indexEntry(code, LAPS.filter((row) => row.driver_code === code)))
    },
    "telemetry/RUS.json": { driver_code: "RUS", laps: [telemetryLap(2, 17_600)] },
    [`telemetry/${NUMBERED}.json`]: { driver_code: NUMBERED, laps: [telemetryLap(2, 17_500), telemetryLap(3, 17_700)] }
  });
  const view = shareReads(await clientOf(bucket).openSession(SESSION_KEY));
  bucket.requests.length = 0;
  const requested = () => bucket.keys().map((key) => key.slice(generationPrefix(generation).length));
  return { view, requested, drivers };
}

test("a driver published under a car number is compared like any other, from the file the index names", async () => {
  const { view, requested } = await sessionWithNumberedDriver();

  const telemetry = await readTelemetry(view);

  // The quicker of the two, so the first of the pair.
  assert.deepEqual(telemetry.pair, [
    { driver: NUMBERED, lap: 2 },
    { driver: "RUS", lap: 2 }
  ]);
  assert.deepEqual(telemetry.comparison.driver_a, { driver_code: NUMBERED, team: null, lap_number: 2, lap_time_ms: 70_300, compound: "MEDIUM" });
  assert.deepEqual(telemetry.comparison.delta_time_ms, [0, 100, 200, 300, 400]);
  assert.ok(requested().includes(`telemetry/${NUMBERED}.json`));

  const own = await compareTelemetry(view, { driver: NUMBERED, lap: 3 }, { driver: NUMBERED, lap: 2 });
  assert.equal(own.driver_a.driver_code, NUMBERED);
  assert.deepEqual(own.delta_time_ms, [0, -200, -400, -600, -800]);
});

test("a car number sorts and ties like a code", () => {
  const index = { drivers: ["RUS", NUMBERED, "ALB"].map((code) => indexEntry(code, [lap(code, 1, 70_000)])) };

  // Three drivers on the same time: the tie goes by code, and a number comes before a letter.
  assert.deepEqual(defaultComparison(telemetryLaps(index)), [
    { driver: NUMBERED, lap: 1 },
    { driver: "ALB", lap: 1 }
  ]);
  assert.deepEqual(
    fastestLapByDriver([lap("RUS", 1, 70_000), lap(NUMBERED, 1, 70_000), lap("ALB", 1, 70_000)]).map((row) => row.driver_code),
    [NUMBERED, "ALB", "RUS"]
  );
  assert.deepEqual(tyreAgePlot(LAPS).drivers.map((entry) => entry.driver), [NUMBERED, "RUS"]);
});

test("a driver with a number for a code is styled, grouped and charted under it", () => {
  const drivers = [
    { code: "RUS", team: { color: "#00D7B6" } },
    { code: NUMBERED, team: null },
    { code: "7", team: { color: "#00D7B6" } }
  ];
  const styles = teamDriverStyles(drivers);

  assert.equal(driverStyle(styles, NUMBERED).color, FALLBACK_DRIVER_COLOR);
  // Two cars in one colour are told apart whatever their codes are made of.
  assert.notEqual(driverStyle(styles, "7").dash, driverStyle(styles, "RUS").dash);
  assert.equal(teamColorByDriver(drivers)[NUMBERED], undefined);
  assert.equal(teamColorByDriver(drivers)["7"], "#00D7B6");

  assert.deepEqual(groupByDriver(LAPS).map(([code, rows]) => [code, rows.length]), [["RUS", 1], [NUMBERED, 2]]);
  // The chart's rows are keyed by code beside the lap number, and a code that
  // is a number does not take the lap's place or lose its own.
  assert.deepEqual(
    seriesToRows([
      { name: "RUS", color: null, x: [1, 2], y: [71_000, 70_500] },
      { name: NUMBERED, color: null, x: [2], y: [70_300] }
    ]),
    [
      { lap: 1, RUS: 71_000, [NUMBERED]: null },
      { lap: 2, RUS: 70_500, [NUMBERED]: 70_300 }
    ]
  );
});

test("a numbered driver's stops, minisectors and result are matched by the number", () => {
  const stop = { driver_code: NUMBERED, lap_number: 21, entry_time_ms: 1, duration_ms: 21_000, stationary_ms: null, pit_lane_ms: null, under_red_flag: false, sources: { duration_ms: "timing", stationary_ms: null, pit_lane_ms: null } };
  const strategy = {
    compound_usage: {},
    pit_lane_time: { median_ms: 21_000, fastest_ms: 21_000, slowest_ms: 21_000, timed_stop_count: 1, stop_count: 1 },
    pit_loss: {
      estimate_ms: null,
      spread_ms: null,
      qualifying_stop_count: 1,
      stop_count: 1,
      minimum_stop_count: 3,
      baseline_window_laps: 5,
      excluded_stop_counts: {},
      stops: [{ driver_code: NUMBERED, lap_number: 21, pit_loss_ms: 20_500, excluded_reason: null, in_lap_ms: null, out_lap_ms: null, baseline_lap_ms: null, baseline_lap_count: 5 }]
    },
    pit_loss_estimate_ms: null,
    undercut_overcut: [],
    caveats: []
  };
  assert.deepEqual(pitStopLog(strategy, [stop])[0].pitLoss, { status: "estimated", pit_loss_ms: 20_500 });

  const sector = (index, winner, times) => ({ index, start_distance_m: 0, end_distance_m: 1, midpoint: { x: 0, y: 0 }, winner_driver_code: winner, segment_time_ms: null, gap_to_next_ms: null, driver_times_ms: times });
  assert.deepEqual(
    minisectorTally({ caveats: [], excluded_drivers: [], minisector_count: 2, representative_laps: [], minisectors: [sector(1, NUMBERED, { [NUMBERED]: 2000, RUS: 2010 }), sector(2, "RUS", { RUS: 1990 })] }),
    [
      { driver: NUMBERED, won: 1, timed: 1 },
      { driver: "RUS", won: 1, timed: 2 }
    ]
  );

  // The classification does not name the driver, so the row has no position.
  const unplaced = { driver_code: NUMBERED, position: null, classified_position: null, time_ms: null, gap_ms: null, laps_down: null, behind_at_flag_ms: null, grid: null, laps: null, points: null, status: null, provisional: false };
  assert.equal(resultPosition(unplaced).text, "--");
});

test("a numbered driver has a card, and is listed with the drivers no team is named for", async () => {
  const { drivers } = await sessionWithNumberedDriver();
  const field = { drivers, results: null, racePace: null, idealLaps: null };

  assert.deepEqual(driverCards(field).map((card) => card.driver.code), ["RUS", NUMBERED]);
  assert.deepEqual(teamCards(field).map((card) => [card.name, card.drivers.map((driver) => driver.code)]), [
    ["Mercedes", ["RUS"]],
    ["No team listed", [NUMBERED]]
  ]);
});
