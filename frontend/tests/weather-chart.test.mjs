import assert from "node:assert/strict";
import test from "node:test";

import {
  describeWeatherPlot,
  hasTemperatures,
  sampleNote,
  sessionClockTicks,
  weatherPlot
} from "../src/lib/weather-chart.ts";

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

// F1's feed can leave a sensor out of a sample. FastF1 hands that on as a
// zero, and the publisher used to publish the zero: a track at 0 degrees, and
// a sample that "was dry" because nothing said it was raining.
test("a missing reading stays missing and is not drawn as zero", () => {
  const plot = weatherPlot([sample(30_000, { air_temp_c: null, track_temp_c: null, humidity_pct: null, wind_speed_kph: null, rainfall: null })]);

  assert.deepEqual(plot.points[0], {
    time_ms: 30_000,
    lap_number: null,
    air_temp_c: null,
    track_temp_c: null,
    humidity_pct: null,
    wind_speed_kph: null,
    rainfall: null
  });
  assert.equal(hasTemperatures(plot), false);
});

test("a sample with one temperature and not the other is still drawn, and the gap is said", () => {
  const plot = weatherPlot([
    sample(30_000),
    sample(90_000, { track_temp_c: null }),
    sample(150_000, { air_temp_c: null, track_temp_c: null }),
    sample(210_000)
  ]);

  assert.equal(hasTemperatures(plot), true);
  assert.deepEqual([plot.airCount, plot.trackCount], [3, 2]);
  assert.equal(
    describeWeatherPlot(plot),
    "4 samples. 1 without an air temperature and 2 without a track temperature: the line breaks there. No rain was recorded."
  );
});

test("samples with no temperature at all are described, and there is nothing to draw", () => {
  const plot = weatherPlot([sample(30_000, { air_temp_c: null, track_temp_c: null }), sample(90_000, { air_temp_c: null, track_temp_c: null })]);

  assert.equal(hasTemperatures(plot), false);
  assert.equal(describeWeatherPlot(plot), "2 samples. None has an air or a track temperature. No rain was recorded.");
  assert.equal(hasTemperatures(weatherPlot([])), false);
});

// In a race a sample says which lap the leader was on; before the start,
// after the flag and in any other session it has none.
test("under the pointer a sample says its lap and whether it was raining, each only if it knows", () => {
  const plot = weatherPlot([
    sample(3_300_000),
    sample(3_480_000, { lap_number: 1, rainfall: true }),
    sample(5_400_000, { lap_number: 34, rainfall: null }),
    sample(9_000_000, { rainfall: null })
  ]);

  assert.equal(sampleNote(plot, 3_300_000), " · dry");
  assert.equal(sampleNote(plot, 3_480_000), " · lap 1 · raining");
  // It does not say whether it was raining, and so neither does the page.
  assert.equal(sampleNote(plot, 5_400_000), " · lap 34");
  assert.equal(sampleNote(plot, 9_000_000), "");
  // A time no sample was taken at, as a chart reports while the pointer moves.
  assert.equal(sampleNote(plot, 4_000_000), "");
});

test("the description says how many samples there are and whether it rained", () => {
  const dry = weatherPlot([sample(30_000), sample(330_000)]);
  const wet = weatherPlot([sample(30_000), sample(330_000, { rainfall: true })]);

  assert.equal(describeWeatherPlot(dry), "2 samples. No rain was recorded.");
  assert.equal(describeWeatherPlot(wet), "2 samples. Rain was recorded in 1 of 2 samples.");
  assert.equal(describeWeatherPlot(weatherPlot([sample(30_000)])), "1 sample. No rain was recorded.");
  assert.equal(describeWeatherPlot(weatherPlot([])), "No weather samples in this session.");
});

// "No rain was recorded" over samples that do not say would be a claim
// nobody measured.
test("a sample that does not say whether it rained is not counted as dry", () => {
  const some = weatherPlot([sample(30_000), sample(90_000, { rainfall: null }), sample(150_000, { rainfall: null })]);
  const wet = weatherPlot([sample(30_000, { rainfall: true }), sample(90_000), sample(150_000, { rainfall: null })]);
  const none = weatherPlot([sample(30_000, { rainfall: null }), sample(90_000, { rainfall: null })]);

  assert.deepEqual([some.rainCount, some.rainKnownCount], [0, 1]);
  assert.equal(describeWeatherPlot(some), "3 samples. No rain was recorded in the 1 that say. 2 do not say whether it was raining.");
  assert.equal(describeWeatherPlot(wet), "3 samples. Rain was recorded in 1 of the 2 that say. 1 does not say whether it was raining.");
  assert.equal(describeWeatherPlot(none), "2 samples. None says whether it was raining.");
  assert.equal(describeWeatherPlot(weatherPlot([sample(30_000, { rainfall: null })])), "1 sample. It does not say whether it was raining.");
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
