import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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

// A lap's distance does not start at nought: it is counted from the sample
// before the line, and the line falls a fraction of a metre either side.
test("two laps are laid over each other from where each one's distance starts", () => {
  const a = lap(3, [[0, 0, 180], [50_000, 2_500, 180], [100_000, 5_000, 180]]);
  // The same lap, by an odometer that read 0.4 m less at the line.
  const b = lap(2, [[0, -0.4, 180], [50_000, 2_499.6, 180], [100_000, 4_999.6, 180]]);

  // Laid over from nought, B was 8 ms behind at the line it started on, and 4 half-way round.
  assert.deepEqual(compare(a, b).delta_time_ms, [0, 0, 0]);
  assert.deepEqual(compare(b, a).delta_time_ms, [0, 0, 0]);
  // And a longer odometer is still stretched over the shorter, from its own start.
  const longer = lap(4, [[0, 0.5, 180], [50_000, 2_525.5, 180], [100_000, 5_050.5, 180]]);
  assert.deepEqual(compare(a, longer).delta_time_ms, [0, 0, 0]);
});

// The first answer to that shifted each place as it was looked up: B's
// origin, plus A's distance less A's origin. For a lap laid over itself that
// is -1 + (4095.1 - -1), which is 4095.1000000000004 and not 4095.1: a hair
// past the place the car stood at, so it was read as having left.
function lapStandingStill(origin, standsAt = 4_095.1) {
  const samples = [];
  let distance = origin;
  for (let index = 0; index <= 240; index += 1) {
    const time = index * 500;
    const standing = time >= 100_000 && time <= 104_000;
    if (index > 0 && !standing) {
      // Up to thirty metres short of its box, then into it; and away again after.
      distance = time < 100_000 ? origin + ((standsAt - 30 - origin) * time) / 99_500 : distance + 25.3;
    }
    if (time === 100_000) {
      distance = standsAt;
    }
    samples.push([time, distance, standing ? 0 : 180]);
  }
  return lap(30, samples);
}

for (const origin of [0, -1, -0.7, -0.4, 0.3, 0.4, 0.1 + 0.2]) {
  test(`a lap that starts at ${origin} m and stands still is nowhere apart from itself`, () => {
    const standing = lapStandingStill(origin);
    // Four seconds in its box: the sample it arrives at, and every one until it leaves.
    assert.equal(standing.distance_m.filter((distance) => distance === 4_095.1).length, 9);

    const comparison = compare(standing, standing);

    assert.deepEqual(comparison.delta_time_ms, standing.time_ms.map(() => 0));
    assert.deepEqual(comparison.speed_b, comparison.speed_a);
    // The chart's distances are the lap's own, as published.
    assert.deepEqual(comparison.distance_m, standing.distance_m);
  });
}

test("a lap with a hole in it is nowhere apart from itself either, whatever its distance reads at the line", () => {
  for (const origin of [0, -1, 0.4]) {
    const samples = [];
    for (let index = 0; index <= 60; index += 1) {
      const time = index < 30 ? index * 250 : 6_500 + index * 250;
      samples.push([time, origin + time * 0.0531, 190]);
    }
    const holed = lap(12, samples);

    const comparison = compare(holed, holed);

    // One row with nothing in it, where the hole is, and nothing else amiss.
    assert.equal(comparison.delta_time_ms.filter((delta) => delta === null).length, 1, String(origin));
    assert.equal(comparison.delta_time_ms.every((delta) => delta === null || delta === 0), true, String(origin));
  }
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

// ---------------------------------------------------------------------------
// Standing still
// ---------------------------------------------------------------------------

// Bearman's lap 30 of the 2026 Canadian GP, as pipeline 9 published it: the
// sixty samples from the last metres into his pit box to the first metres
// out of it. Fifty-two of them are at 4117.8 m, the car standing for 23
// seconds, and the one after those is at 4117.7 m: the distance steps back a
// tenth of a metre as the car is released.
const BEARMAN = JSON.parse(readFileSync(new URL("./fixtures/telemetry-11291-BEA-lap-30.json", import.meta.url), "utf8"));
const CHANNELS = ["speed", "throttle", "brake", "rpm", "gear"];

// Looked up as published, the sample at 4117.7 m was found between the two
// samples on the way in, 4117.4 m and 4117.8 m: the lap was 4.15 km/h and
// 23,416.3 ms apart from itself there, and wrong at fifty other samples.
test("a lap compared with itself is the same lap at every sample, through a pit stop", () => {
  const lap30 = BEARMAN.lap;
  const released = lap30.time_ms.indexOf(123_521);
  assert.deepEqual(lap30.distance_m.slice(released - 3, released + 2), [4117.8, 4117.8, 4117.8, 4117.7, 4118.7]);
  assert.equal(lap30.speed_kph[released], 0);

  const comparison = compare(lap30, lap30);

  assert.equal(comparison.distance_m.length, BEARMAN.sample_count);
  assert.deepEqual(comparison.delta_time_ms, lap30.time_ms.map(() => 0));
  assert.deepEqual(comparison.delta_speed_kph, lap30.time_ms.map(() => 0));
  for (const channel of CHANNELS) {
    assert.deepEqual(comparison[`${channel}_b`], comparison[`${channel}_a`], channel);
  }
  assert.deepEqual(comparison.speed_a, lap30.speed_kph);
  assert.deepEqual(comparison.rpm_a, lap30.rpm);
  // The sample that was 23 seconds from itself.
  assert.deepEqual(
    [comparison.speed_a[released], comparison.speed_b[released], comparison.delta_time_ms[released]],
    [0, 0, 0]
  );
});

test("a lap's distance is read as the furthest the car had got, so it never goes down", () => {
  const comparison = compare(BEARMAN.lap, BEARMAN.lap);
  const released = BEARMAN.lap.time_ms.indexOf(123_521);

  assert.equal(comparison.distance_m[released], 4117.8);
  assert.deepEqual([...comparison.distance_m].sort((left, right) => left - right), comparison.distance_m);
  // The same for a lap it is compared with: a place a tenth of a metre back
  // is not looked for on the way in.
  const a = lap(3, [[0, 0, 200], [1_000, 100, 200], [2_000, 200, 200], [3_000, 300, 200]]);
  const b = lap(2, [[0, 0, 200], [1_000, 100, 60], [9_000, 99.9, 0], [10_000, 200, 200], [11_000, 300, 200]]);
  assert.deepEqual(compare(a, b).delta_time_ms, [0, 0, 8_000, 8_000]);
});

/**
 * A lap of 1,000 m at 100 km/h with a stop at 500 m: there after 5 s, away
 * again `stopMs` later, with a sample every second while it stands.
 */
function lapWithStop(number, stopMs) {
  const standing = Array.from({ length: stopMs / 1_000 + 1 }, (_, second) => [5_000 + second * 1_000, 500, 0]);
  return lap(number, [[0, 0, 100], [2_500, 250, 100], ...standing, [7_500 + stopMs, 750, 100], [10_000 + stopMs, 1_000, 100]]);
}

test("two cars standing at one place are compared moment for moment of the stop, and by the difference afterwards", () => {
  const long = lapWithStop(1, 10_000);
  const short = lapWithStop(2, 4_000);

  // A stands for ten seconds and B for four. For four seconds they are level;
  // then B is away, and A loses a second for each second it still stands.
  assert.deepEqual(compare(long, short).delta_time_ms, [0, 0, 0, 0, 0, 0, 0, -1_000, -2_000, -3_000, -4_000, -5_000, -6_000, -6_000, -6_000]);
  // The other way about, A is away after four seconds with B still standing:
  // level while A stands, and B six seconds behind from the next place on.
  assert.deepEqual(compare(short, long).delta_time_ms, [0, 0, 0, 0, 0, 0, 0, 6_000, 6_000]);
});

test("a car standing where the other drives through is read as it arrives, and its stop is in the delta after", () => {
  const through = lap(1, [[0, 0, 100], [2_500, 250, 100], [5_000, 500, 100], [7_500, 750, 100], [10_000, 1_000, 100]]);
  const stopped = lapWithStop(2, 4_000);

  // A passes 500 m once. B reached it at the same moment, and left four seconds later.
  assert.deepEqual(compare(through, stopped).delta_time_ms, [0, 0, 0, 4_000, 4_000]);
  assert.deepEqual(compare(through, stopped).speed_b, [100, 100, 0, 100, 100]);
  // And a car standing where the other does not: it falls behind while it stands.
  assert.deepEqual(compare(stopped, through).delta_time_ms, [0, 0, 0, -1_000, -2_000, -3_000, -4_000, -4_000, -4_000]);
});

test("a car standing at the start of a lap is compared from the moment it was first there", () => {
  const a = lap(3, [[0, 0, 200], [1_000, 100, 200]]);
  const b = lap(2, [[0, 0, 0], [500, 0, 0], [900, 0, 60], [1_900, 100, 200]]);

  // B stood at the line for 900 ms. A was not standing, so B is read as it
  // was first there, and the time it stood is in the delta at the next place.
  assert.deepEqual(compare(a, b).delta_time_ms, [0, 900]);
  assert.deepEqual(compare(a, b).speed_b, [0, 200]);
});

// A lap with no standstill is read exactly as before: this is the plain
// interpolation, written out again.
test("laps that never stand still are compared as they always were", () => {
  const samplesOf = (count, pace, wobble) =>
    Array.from({ length: count }, (_, index) => [
      Math.round(index * pace + wobble * Math.sin(index)),
      Number((index * 14.3 + wobble * 0.01 * Math.sin(index * 1.7)).toFixed(1)),
      200 + (index % 7) * 9
    ]);
  const a = lap(3, samplesOf(40, 250, 20));
  const b = lap(2, samplesOf(37, 271, 30));
  const scale = b.distance_m.at(-1) / a.distance_m.at(-1);
  const plainly = (channel) =>
    a.distance_m.map((distance, index) => {
      const place = index === a.distance_m.length - 1 ? b.distance_m.at(-1) : distance * scale;
      let low = 0;
      while (low < b.distance_m.length - 1 && b.distance_m[low + 1] <= place) {
        low += 1;
      }
      if (b.distance_m[low] === place) {
        return b[channel][low];
      }
      const share = (place - b.distance_m[low]) / (b.distance_m[low + 1] - b.distance_m[low]);
      return b[channel][low] + (b[channel][low + 1] - b[channel][low]) * share;
    });

  const comparison = compare(a, b);

  assert.deepEqual(comparison.speed_b, plainly("speed_kph"));
  assert.deepEqual(comparison.delta_time_ms, plainly("time_ms").map((time, index) => Math.round((time - a.time_ms[index]) * 10) / 10));
  assert.deepEqual(comparison.distance_m, a.distance_m);
});

// ---------------------------------------------------------------------------
// A channel that says nothing of a sample
// ---------------------------------------------------------------------------

// The schema lets a channel be shorter than the lap's clock. Read past its
// end, a brake was "off" and a DRS flap "closed" where nothing said so.
test("a channel with no entry for a sample has no value there, not a zero", () => {
  const samples = [[0, 0, 200], [1_000, 100, 210], [2_000, 200, 220]];
  const short = lap(3, samples, { brake: [true], drs: [12, 12], speed_kph: [200, 210], gear: [7], rpm: [], throttle_pct: [100, 90] });
  const whole = lap(2, samples, { brake: [true, true, true], drs: [12, 12, 12] });

  const comparison = compare(short, whole);

  assert.deepEqual(comparison.brake_a, [1, null, null]);
  assert.deepEqual(comparison.drs_a, [1, 1, null]);
  assert.deepEqual(comparison.speed_a, [200, 210, null]);
  assert.deepEqual(comparison.gear_a, [7, null, null]);
  assert.deepEqual(comparison.rpm_a, [null, null, null]);
  assert.deepEqual(comparison.throttle_a, [100, 90, null]);
  // What cannot be known of one lap is not known of the difference either.
  assert.deepEqual(comparison.delta_speed_kph, [0, 0, null]);
  // The lap that has its channels is read in full, and the clocks still compare.
  assert.deepEqual(comparison.brake_b, [1, 1, 1]);
  assert.deepEqual(comparison.delta_time_ms, [0, 0, 0]);
  assert.deepEqual(telemetryRows(comparison).map((row) => [row.brakeA, row.drsA]), [[1, 1], [null, 1], [null, null]]);
});

test("a short channel of the lap that is looked up is unknown too, between samples as at them", () => {
  const a = lap(3, [[0, 0, 200], [1_000, 50, 200], [2_000, 100, 200], [3_000, 150, 200], [4_000, 200, 200]]);
  const b = lap(2, [[0, 0, 100], [2_000, 100, 120], [4_000, 200, 140]], { brake: [false, true], speed_kph: [100, 120], drs: [0] });

  const comparison = compare(a, b);

  // Half-way to a sample that has no speed, there is no speed to interpolate.
  assert.deepEqual(comparison.speed_b, [100, 110, 120, null, null]);
  // Taken from the nearer sample: known until the nearer one is the one without.
  assert.deepEqual(comparison.brake_b, [0, 1, 1, null, null]);
  assert.deepEqual(comparison.drs_b, [0, null, null, null, null]);
});

test("a lap whose distances stop short of its clock is compared over the samples that have both", () => {
  const whole = lap(3, [[0, 0, 200], [1_000, 100, 210], [2_000, 200, 220]]);
  const cut = { ...whole, distance_m: [0, 100] };

  // The third sample has a time and no place, so it is nowhere to be drawn or looked up.
  const comparison = compare(cut, cut);
  assert.deepEqual(comparison.distance_m, [0, 100]);
  assert.deepEqual(comparison.speed_a, [200, 210]);
  assert.deepEqual(comparison.delta_time_ms, [0, 0]);
  // Against the whole lap, its 100 m are the whole lap's 200 m: laps are laid over each other by share.
  assert.deepEqual(compare(whole, cut).delta_time_ms, [0, -500, -1_000]);
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
