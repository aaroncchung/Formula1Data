import assert from "node:assert/strict";
import test from "node:test";

import { describeWeatherPlot, lapAt, sessionClockTicks, weatherPlot } from "../src/lib/weather-chart.ts";

/** A weather sample as weather.json has one, taken at `time` on the session clock. */
function sample(time, overrides = {}) {
  return {
    time_ms: time,
    lap_number: null,
    air_temp_c: 33.6,
    track_temp_c: 53.2,
    humidity_pct: 30.3,
    rainfall: false,
    wind_speed_kph: 1.0,
    ...overrides
  };
}

// The defect this once replaced: the chart's X axis was a lap number that
// every sample lacked, so all thirty points shared one place.
test("samples are placed by the session clock they carry", () => {
  const plot = weatherPlot([
    sample(38_376),
    sample(338_406, { track_temp_c: 53.0 }),
    sample(8_739_996, { air_temp_c: 34.0 })
  ]);

  assert.deepEqual(
    plot.points.map((point) => point.time_ms),
    [38_376, 338_406, 8_739_996]
  );
  assert.deepEqual(plot.points[1], {
    time_ms: 338_406,
    lap_number: null,
    air_temp_c: 33.6,
    track_temp_c: 53.0,
    humidity_pct: 30.3,
    wind_speed_kph: 1.0,
    rainfall: false
  });
});

test("samples are plotted in time order whatever order they arrive in", () => {
  const plot = weatherPlot([sample(600_000), sample(30_000), sample(300_000)]);

  assert.deepEqual(
    plot.points.map((point) => point.time_ms),
    [30_000, 300_000, 600_000]
  );
});

test("a missing reading stays missing and is not drawn as zero", () => {
  const plot = weatherPlot([sample(30_000, { air_temp_c: null, track_temp_c: null, humidity_pct: null })]);

  assert.equal(plot.points[0].air_temp_c, null);
  assert.equal(plot.points[0].track_temp_c, null);
  assert.equal(plot.points[0].humidity_pct, null);
});

// In a race a sample says which lap the leader was on; before the start,
// after the flag and in any other session it has none.
test("a sample's lap is kept beside its time, and is absent where the race was not running", () => {
  const plot = weatherPlot([sample(3_300_000), sample(3_480_000, { lap_number: 1 }), sample(5_400_000, { lap_number: 34 })]);

  assert.equal(lapAt(plot, 3_300_000), null);
  assert.equal(lapAt(plot, 3_480_000), 1);
  assert.equal(lapAt(plot, 5_400_000), 34);
  // A time no sample was taken at, as a chart reports while the pointer moves.
  assert.equal(lapAt(plot, 4_000_000), null);
});

test("the description says how many samples there are and whether it rained", () => {
  const dry = weatherPlot([sample(30_000), sample(330_000)]);
  const wet = weatherPlot([sample(30_000), sample(330_000, { rainfall: true })]);

  assert.equal(describeWeatherPlot(dry), "2 samples. No rain was recorded.");
  assert.equal(describeWeatherPlot(wet), "2 samples. Rain was recorded in 1 of 2 samples.");
  assert.equal(describeWeatherPlot(weatherPlot([sample(30_000)])), "1 sample. No rain was recorded.");
  assert.equal(describeWeatherPlot(weatherPlot([])), "No weather samples in this session.");
});

test("the samples a page was given are not put in another order", () => {
  const samples = Object.freeze([sample(600_000), sample(30_000)]);

  weatherPlot(samples);

  assert.deepEqual(samples.map((item) => item.time_ms), [600_000, 30_000]);
});

const minutes = (ticks) => ticks.map((tick) => tick / 60_000);

test("axis marks fall on round minutes of the session clock", () => {
  // A race: samples from 0:00:38 to 2:25:39.
  assert.deepEqual(minutes(sessionClockTicks(38_376, 8_739_996)), [20, 40, 60, 80, 100, 120, 140]);
  // A short session keeps to a smaller step.
  assert.deepEqual(minutes(sessionClockTicks(0, 30 * 60_000)), [0, 5, 10, 15, 20, 25, 30]);
  assert.deepEqual(minutes(sessionClockTicks(60_000, 6 * 60_000)), [1, 2, 3, 4, 5, 6]);
});

test("axis marks never outnumber the limit, and an empty range has none", () => {
  for (const hours of [0.5, 1, 2, 3, 6, 12]) {
    const ticks = sessionClockTicks(0, hours * 3_600_000);
    assert.ok(ticks.length >= 2 && ticks.length <= 8, `${hours} h gave ${ticks.length} marks`);
  }
  assert.deepEqual(sessionClockTicks(5_000, 5_000), []);
  assert.deepEqual(sessionClockTicks(9_000, 5_000), []);
  assert.deepEqual(sessionClockTicks(Number.NaN, 5_000), []);
});
