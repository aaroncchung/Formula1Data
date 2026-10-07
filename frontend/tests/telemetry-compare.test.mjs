import assert from "node:assert/strict";
import test from "node:test";

import { telemetryRows } from "../src/lib/chart-utils.ts";
import { compareLaps, holeThresholdMs, trackOf } from "../src/lib/telemetry-compare.ts";

/**
 * A telemetry lap in the published shape, from one row for each sample:
 * `[time_ms, distance_m, speed_kph]`, with the other channels the same
 * throughout unless `channels` gives them.
 */
function lap(number, samples, channels = {}) {
  const constant = (value) => samples.map(() => value);
  return {
    lap_number: number,
    start_ms: 3_500_000,
    time_ms: samples.map((sample) => sample[0]),
    distance_m: samples.map((sample) => sample[1]),
    speed_kph: samples.map((sample) => sample[2]),
    throttle_pct: constant(100),
    brake: constant(false),
    rpm: constant(11_000),
    gear: constant(7),
    drs: null,
    x: null,
    y: null,
    ...channels
  };
}

const meta = (driver, number) => ({ driver_code: driver, team: null, lap_number: number, lap_time_ms: null, compound: null });
const compare = (a, b) => compareLaps({ meta: meta("RUS", a.lap_number), lap: a }, { meta: meta("VER", b.lap_number), lap: b }, 300);

// ---------------------------------------------------------------------------
// Laying one lap over the other
// ---------------------------------------------------------------------------

test("lap B is read where lap A's samples are, between its own two samples either side", () => {
  const a = lap(3, [[0, 0, 200], [1_000, 50, 210], [2_000, 110, 230], [3_000, 200, 250]]);
  // B's samples fall at other places: 0, 100 and 200 m.
  const b = lap(2, [[0, 0, 100], [2_000, 100, 200], [4_000, 200, 300]]);

  const comparison = compare(a, b);

  assert.deepEqual(comparison.distance_m, [0, 50, 110, 200]);
  assert.deepEqual(comparison.speed_a, [200, 210, 230, 250]);
  // Half-way between 100 and 200 km/h at 50 m; a tenth of the way to 300 at 110 m.
  assert.deepEqual(comparison.speed_b, [100, 150, 210, 300]);
  assert.deepEqual(comparison.delta_speed_kph, [100, 60, 20, -50]);
});

// The point of interpolating: with 300 samples a lap, the nearest sample is
// up to an eighth of a second away, which is more than most gaps being read.
test("the time delta is how much later B reached each distance, interpolated and not taken from the nearest sample", () => {
  const a = lap(3, [[0, 0, 200], [1_000, 50, 200], [2_000, 110, 200], [3_000, 200, 200]]);
  const b = lap(2, [[0, 0, 100], [2_000, 100, 100], [4_000, 200, 100]]);

  const comparison = compare(a, b);

  // B is at 50 m after 1,000 ms, at 110 m after 2,200 ms and at the line after 4,000 ms.
  assert.deepEqual(comparison.delta_time_ms, [0, 0, 200, 1000]);
});

// The 2026 Austrian GP, as published: Antonelli's lap 59 took 70.374 s and its
// samples add up to 4,290.6 m; Verstappen's lap 57 took 70.483 s and adds up
// to 4,309.8 m. It is one circuit, and the odometers disagree by 19 m. Read
// metre for metre, Verstappen is 19 m short of the line when Antonelli
// crosses it, and the slower lap is drawn as finishing a tenth ahead.
test("two laps end together, and the delta at the line is the difference between the lap times", () => {
  const antonelli = lap(59, [[0, 0, 280], [35_000, 2_145.3, 250], [70_374, 4_290.6, 290]]);
  const verstappen = lap(57, [[0, 0, 280], [35_300, 2_154.9, 250], [70_483, 4_309.8, 290]]);

  const comparison = compare(antonelli, verstappen);

  // Half-way round is half-way round for both, whatever each odometer says.
  assert.deepEqual(comparison.delta_time_ms, [0, 300, 109]);
  assert.deepEqual(comparison.speed_b, [280, 250, 290]);
  // The axis is lap A's own distance.
  assert.deepEqual(comparison.distance_m, [0, 2_145.3, 4_290.6]);
  // And the other way about, the same gap with the other sign.
  assert.deepEqual(compare(verstappen, antonelli).delta_time_ms, [0, -300, -109]);
});

test("the comparison says how long each lap's odometer made it", () => {
  const antonelli = lap(59, [[0, 0, 280], [70_374, 4_290.6, 290]]);
  const verstappen = lap(57, [[0, 0, 280], [70_483, 4_309.8, 290]]);

  assert.match(compare(antonelli, verstappen).caveats[0], /4,291 m for RUS and 4,310 m for VER here, so VER's is scaled to RUS's/);
});

test("a positive time delta is B behind A, a negative one B ahead", () => {
  const slow = lap(1, [[0, 0, 200], [1_000, 100, 200], [2_000, 200, 200]]);
  const fast = lap(1, [[0, 0, 220], [900, 100, 220], [1_800, 200, 220]]);

  assert.deepEqual(compare(fast, slow).delta_time_ms, [0, 100, 200]);
  assert.deepEqual(compare(slow, fast).delta_time_ms, [0, -100, -200]);
});

test("gear, brake and DRS are taken from the nearer of B's two samples, never from between them", () => {
  const a = lap(3, [[0, 0, 200], [400, 40, 200], [600, 60, 200], [1_000, 100, 200]]);
  const b = lap(2, [[0, 0, 200], [1_000, 100, 200]], { gear: [3, 4], brake: [true, false], drs: [8, 12] });

  const comparison = compare(a, b);

  assert.deepEqual(comparison.gear_b, [3, 3, 4, 4]);
  assert.deepEqual(comparison.brake_b, [1, 1, 0, 0]);
  assert.deepEqual(comparison.drs_b, [0, 0, 1, 1]);
});

test("B has no value before its first sample", () => {
  const a = lap(3, [[0, 0, 200], [1_000, 100, 200], [2_000, 200, 200], [3_000, 300, 200]]);
  // B's first sample is 20 m into its lap.
  const b = lap(2, [[300, 20, 180], [1_500, 150, 190], [3_100, 300, 200]]);

  const comparison = compare(a, b);

  assert.equal(comparison.speed_b[0], null);
  assert.equal(comparison.delta_time_ms[0], null);
  assert.notEqual(comparison.speed_b[1], null);
  assert.equal(comparison.delta_time_ms[3], 100);
  // A's own values are all there.
  assert.deepEqual(comparison.speed_a, [200, 200, 200, 200]);
});

test("a sample of B at exactly A's distance is read as it is", () => {
  const a = lap(3, [[0, 0, 200], [1_000, 100, 210]]);
  const b = lap(2, [[0, 0, 150], [1_100, 100, 160]], { gear: [5, 6] });

  const comparison = compare(a, b);

  assert.deepEqual(comparison.speed_b, [150, 160]);
  assert.deepEqual(comparison.gear_b, [5, 6]);
  assert.deepEqual(comparison.delta_time_ms, [0, 100]);
});

test("a car standing still has several samples at one distance, and is read at the last of them", () => {
  const a = lap(3, [[0, 0, 200], [1_000, 100, 200]]);
  const b = lap(2, [[0, 0, 0], [500, 0, 0], [900, 0, 60], [1_900, 100, 200]]);

  assert.deepEqual(compare(a, b).delta_time_ms, [900, 900]);
});

// ---------------------------------------------------------------------------
// Holes
// ---------------------------------------------------------------------------

// A lap can lack a stretch of car data. The publisher leaves the stretch out;
// it does not fill it with zeros, and neither does the page.
const STEADY = [[0, 0, 200], [250, 14, 200], [500, 28, 200], [750, 42, 200], [1_000, 56, 200]];
const AFTER_HOLE = [[6_000, 340, 210], [6_250, 355, 210], [6_500, 370, 210]];

test("two samples seconds apart have a hole between them", () => {
  assert.equal(holeThresholdMs(STEADY.map((sample) => sample[0])), 2_000);
  // A lap so long that its usual step is seconds, as one behind a red flag is:
  // the step itself is not a hole.
  assert.equal(holeThresholdMs([0, 5_000, 10_000, 15_000, 20_000]), 20_000);
  assert.equal(holeThresholdMs([]), 2_000);
  assert.equal(holeThresholdMs([0]), 2_000);
});

test("nothing of lap B is interpolated across a hole in it", () => {
  const a = lap(3, [[0, 0, 200], [1_000, 56, 200], [3_000, 200, 200], [6_000, 340, 200], [6_500, 370, 200]]);
  const b = lap(2, [...STEADY, ...AFTER_HOLE]);

  const comparison = compare(a, b);

  // 200 m is inside B's hole, between its samples at 56 m and 340 m.
  assert.deepEqual(comparison.distance_m.slice(0, 3), [0, 56, 200]);
  assert.equal(comparison.speed_b[2], null);
  assert.equal(comparison.gear_b[2], null);
  assert.equal(comparison.delta_time_ms[2], null);
  // Either side of the hole B is read as usual, at its own samples' edges.
  assert.equal(comparison.speed_b[1], 200);
  assert.equal(comparison.speed_b.at(-1), 210);
});

test("a hole in lap A is a break in every line, at a row with nothing in it", () => {
  const a = lap(3, [...STEADY, ...AFTER_HOLE]);
  const b = lap(2, [[0, 0, 190], [3_000, 180, 190], [7_000, 400, 190]]);

  const comparison = compare(a, b);

  // One more row than A has samples, half-way across the hole.
  assert.equal(comparison.distance_m.length, STEADY.length + AFTER_HOLE.length + 1);
  assert.equal(comparison.distance_m[5], (56 + 340) / 2);
  for (const channel of ["speed_a", "speed_b", "throttle_a", "gear_a", "brake_b", "rpm_a", "delta_time_ms", "delta_speed_kph"]) {
    assert.equal(comparison[channel][5], null, channel);
  }
  assert.equal(comparison.speed_a[4], 200);
  assert.equal(comparison.speed_a[6], 210);
  // Distances still only rise, so the charts' shared axis is in order.
  assert.deepEqual([...comparison.distance_m].sort((left, right) => left - right), comparison.distance_m);
});

// ---------------------------------------------------------------------------
// DRS and positions
// ---------------------------------------------------------------------------

test("a session published without DRS has no DRS to chart, which is not DRS closed", () => {
  const a = lap(3, [[0, 0, 200], [1_000, 100, 200]]);
  const b = lap(2, [[0, 0, 200], [1_000, 100, 200]]);

  const comparison = compare(a, b);

  assert.equal(comparison.drs_a, null);
  assert.equal(comparison.drs_b, null);
  assert.deepEqual(telemetryRows(comparison).map((row) => [row.drsA, row.drsB]), [[null, null], [null, null]]);
});

test("DRS is open for F1's codes 10, 12 and 14, and not for a car that may open it and has not", () => {
  const samples = [[0, 0, 200], [250, 25, 200], [500, 50, 200], [750, 75, 200], [1_000, 100, 200]];
  const a = lap(3, samples, { drs: [0, 8, 10, 12, 14] });

  const comparison = compare(a, a);

  assert.deepEqual(comparison.drs_a, [0, 0, 1, 1, 1]);
  assert.deepEqual(comparison.drs_b, [0, 0, 1, 1, 1]);
});

test("the track drawn is lap A's line, over the samples that have a position", () => {
  const samples = [[0, 0, 200], [500, 50, 200], [1_000, 100, 200]];
  // The position feed can start after the car data does.
  const a = lap(3, samples, { x: [null, 120, 240], y: [null, -30, -60] });

  assert.deepEqual(compare(a, lap(2, samples)).track, [{ x: 120, y: -30 }, { x: 240, y: -60 }]);
  assert.deepEqual(trackOf(lap(3, samples)), []);
  assert.deepEqual(trackOf(lap(3, samples, { x: [1, 2, 3], y: null })), []);
});

test("a comparison says how it was made, and what it can miss", () => {
  const samples = [[0, 0, 200], [1_000, 100, 200]];

  const { caveats, driver_a: driverA, driver_b: driverB } = compare(lap(3, samples), lap(2, samples));

  assert.deepEqual([driverA.driver_code, driverA.lap_number, driverB.driver_code, driverB.lap_number], ["RUS", 3, "VER", 2]);
  assert.match(caveats[0], /laid over each other by the share of the lap covered/);
  assert.match(caveats[1], /VER's lap is read where RUS's samples are/);
  assert.match(caveats[2], /at most 300 samples/);
});

test("an empty lap compares to nothing, without failing", () => {
  const empty = lap(1, []);
  const other = lap(2, [[0, 0, 200], [1_000, 100, 200]]);

  assert.deepEqual(compare(empty, other).distance_m, []);
  assert.deepEqual(compare(other, empty).speed_b, [null, null]);
});
