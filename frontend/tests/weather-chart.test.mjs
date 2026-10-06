import assert from "node:assert/strict";
import test from "node:test";

import { describeWeatherPlot, sessionClockTicks, weatherPlot } from "../src/lib/weather-chart.ts";

function sample(timestamp, overrides = {}) {
  return {
    session_id: "2026-08-r",
    lap_number: null,
    timestamp,
    air_temp_c: 33.6,
    track_temp_c: 53.2,
    humidity_pct: 30.3,
    rainfall: false,
    wind_speed_kph: 1.0,
    ...overrides
  };
}

// The defect this replaces: the chart's X axis was `lap_number`, which is
// null in every published sample, so all thirty points shared one place.
test("samples are placed by the time they carry, not by a lap number they do not have", () => {
  const plot = weatherPlot([
    sample("0 days 00:00:38.376000"),
    sample("0 days 00:05:38.406000", { track_temp_c: 53.0 }),
    sample("0 days 02:25:39.996000", { air_temp_c: 34.0 })
  ]);

  assert.deepEqual(
    plot.points.map((point) => point.time_ms),
    [38_376, 338_406, 8_739_996]
  );
  assert.equal(new Set(plot.points.map((point) => point.time_ms)).size, 3);
  assert.deepEqual(plot.points[1], {
    time_ms: 338_406,
    air_temp_c: 33.6,
    track_temp_c: 53.0,
    humidity_pct: 30.3,
    wind_speed_kph: 1.0,
    rainfall: false
  });
});

test("samples are plotted in time order whatever order they arrive in", () => {
  const plot = weatherPlot([sample("0 days 00:10:00"), sample("0 days 00:00:30"), sample("0 days 00:05:00")]);

  assert.deepEqual(
    plot.points.map((point) => point.time_ms),
    [30_000, 300_000, 600_000]
  );
});

test("a sample whose time cannot be read is left out and counted", () => {
  const plot = weatherPlot([sample("0 days 00:00:30"), sample("NaT"), sample(null), sample("7")]);

  assert.equal(plot.points.length, 1);
  assert.equal(plot.sampleCount, 4);
  assert.equal(plot.untimedCount, 3);
  assert.equal(describeWeatherPlot(plot), "1 of 4 samples plotted; the rest carry no readable time. No rain was recorded.");
});

test("a missing reading stays missing and is not drawn as zero", () => {
  const plot = weatherPlot([sample("0 days 00:00:30", { air_temp_c: null, track_temp_c: undefined, humidity_pct: Number.NaN })]);

  assert.equal(plot.points[0].air_temp_c, null);
  assert.equal(plot.points[0].track_temp_c, null);
  assert.equal(plot.points[0].humidity_pct, null);
});

test("the description says how many samples there are and whether it rained", () => {
  const dry = weatherPlot([sample("0 days 00:00:30"), sample("0 days 00:05:30")]);
  const wet = weatherPlot([sample("0 days 00:00:30"), sample("0 days 00:05:30", { rainfall: true })]);

  assert.equal(describeWeatherPlot(dry), "2 samples. No rain was recorded.");
  assert.equal(describeWeatherPlot(wet), "2 samples. Rain was recorded in 1 of 2 plotted samples.");
  assert.equal(describeWeatherPlot(weatherPlot([])), "No weather samples in this session.");
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
