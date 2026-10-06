import assert from "node:assert/strict";
import test from "node:test";

import { describeTyreAgePlot, isTyreAgePoint, tyreAgePlot, tyreFitsFor } from "../src/lib/tyre-chart.ts";

function lap(driver, number, overrides = {}) {
  return {
    driver_code: driver,
    lap_number: number,
    lap_time_ms: 72000 + number,
    sector_1_ms: null,
    sector_2_ms: null,
    sector_3_ms: null,
    stint: 1,
    position: null,
    track_status: "1",
    compound: "MEDIUM",
    tyre_age: number,
    is_pit_in_lap: false,
    is_pit_out_lap: false,
    is_deleted: false,
    is_accurate: true,
    ...overrides
  };
}

/** A field of `count` drivers named D01, D02, ... with `lapsEach` clean laps each. */
function field(count, lapsEach = 3) {
  const laps = [];
  for (let driver = 1; driver <= count; driver += 1) {
    for (let number = 1; number <= lapsEach; number += 1) {
      laps.push(lap(`D${String(driver).padStart(2, "0")}`, number));
    }
  }
  return laps;
}

// The defect this replaces: the chart kept the first eight drivers it met and
// said nothing about the other fourteen.
test("every driver in the data is in the plot, not the first eight", () => {
  const plot = tyreAgePlot(field(22));

  assert.equal(plot.drivers.length, 22);
  assert.equal(plot.drivers.at(-1)?.driver, "D22");
  assert.ok(plot.drivers.every((entry) => entry.points.length === 3));
  assert.equal(plot.plottedCount, 66);
});

test("drivers are listed by code whatever order their laps arrive in", () => {
  const plot = tyreAgePlot([lap("VER", 1), lap("ALB", 1), lap("RUS", 1), lap("ALB", 2)]);

  assert.deepEqual(
    plot.drivers.map((entry) => entry.driver),
    ["ALB", "RUS", "VER"]
  );
});

test("a plotted lap carries what the tooltip needs", () => {
  const plot = tyreAgePlot([lap("RUS", 14, { tyre_age: 6, lap_time_ms: 72493, compound: "HARD" })]);

  assert.deepEqual(plot.drivers[0].points, [
    { driver_code: "RUS", lap_number: 14, tyre_age: 6, lap_time_ms: 72493, compound: "HARD" }
  ]);
});

test("pit-in and pit-out laps are left out and counted", () => {
  const plot = tyreAgePlot([
    lap("RUS", 1),
    lap("RUS", 2, { is_pit_in_lap: true }),
    lap("RUS", 3, { is_pit_out_lap: true }),
    lap("RUS", 4)
  ]);

  assert.deepEqual(
    plot.drivers[0].points.map((point) => point.lap_number),
    [1, 4]
  );
  assert.equal(plot.pitLapCount, 2);
  assert.equal(plot.incompleteLapCount, 0);
});

test("laps without a lap time or a tyre age are left out and counted", () => {
  const plot = tyreAgePlot([
    lap("RUS", 1, { lap_time_ms: null }),
    lap("RUS", 2, { tyre_age: null }),
    lap("RUS", 3, { lap_time_ms: null, tyre_age: null }),
    lap("RUS", 4, { lap_time_ms: 0 }),
    lap("RUS", 5)
  ]);

  assert.equal(plot.plottedCount, 1);
  assert.equal(plot.incompleteLapCount, 4);
  assert.equal(plot.pitLapCount, 0);
});

test("a tyre age of zero is a measurement, not a missing value", () => {
  const plot = tyreAgePlot([lap("RUS", 1, { tyre_age: 0 })]);

  assert.equal(plot.plottedCount, 1);
  assert.equal(plot.drivers[0].points[0].tyre_age, 0);
});

test("every lap is either plotted or counted as left out", () => {
  const laps = [
    ...field(5, 10),
    lap("D01", 11, { is_pit_in_lap: true }),
    lap("D02", 11, { lap_time_ms: null, is_pit_out_lap: true }),
    lap("D03", 11, { tyre_age: null })
  ];
  const plot = tyreAgePlot(laps);

  assert.equal(plot.lapCount, laps.length);
  assert.equal(plot.plottedCount + plot.pitLapCount + plot.incompleteLapCount, plot.lapCount);
  assert.equal(
    plot.drivers.reduce((sum, entry) => sum + entry.points.length, 0),
    plot.plottedCount
  );
});

test("a driver with laps but nothing to plot stays in the list", () => {
  const plot = tyreAgePlot([lap("RUS", 1), lap("SAI", 1, { is_pit_in_lap: true })]);

  assert.deepEqual(
    plot.drivers.map((entry) => [entry.driver, entry.points.length]),
    [
      ["RUS", 1],
      ["SAI", 0]
    ]
  );
});

test("the description says what was plotted and why the rest was not", () => {
  const laps = [
    ...field(22, 60),
    lap("D01", 61, { is_pit_in_lap: true }),
    lap("D01", 62, { is_pit_out_lap: true }),
    lap("D02", 61, { lap_time_ms: null })
  ];

  assert.equal(
    describeTyreAgePlot(tyreAgePlot(laps)),
    "1,320 of 1,323 laps plotted. Left out: 2 pit-in or pit-out laps and 1 lap without a lap time or tyre age."
  );
});

test("the description names only the reasons that apply", () => {
  assert.equal(
    describeTyreAgePlot(tyreAgePlot([lap("RUS", 1), lap("RUS", 2, { is_pit_in_lap: true })])),
    "1 of 2 laps plotted. Left out: 1 pit-in or pit-out lap."
  );
  assert.equal(describeTyreAgePlot(tyreAgePlot(field(2, 2))), "All 4 laps plotted.");
  assert.equal(describeTyreAgePlot(tyreAgePlot([])), "No laps in this session.");
});

test("the description names a driver that has nothing to plot", () => {
  const plot = tyreAgePlot([lap("RUS", 1), lap("SAI", 1, { is_pit_in_lap: true })]);

  assert.equal(
    describeTyreAgePlot(plot),
    "1 of 2 laps plotted. Left out: 1 pit-in or pit-out lap. Nothing to plot for SAI."
  );
});

test("a tooltip payload is recognised only when it is a plotted lap", () => {
  const point = tyreAgePlot([lap("RUS", 1)]).drivers[0].points[0];

  assert.equal(isTyreAgePoint(point), true);
  assert.equal(isTyreAgePoint({ ...point, compound: null }), true);
  assert.equal(isTyreAgePoint({ ...point, lap_time_ms: null }), false);
  assert.equal(isTyreAgePoint({ x: 1, y: 2 }), false);
  assert.equal(isTyreAgePoint(null), false);
  assert.equal(isTyreAgePoint(undefined), false);
});

function fit(driver, stint) {
  return { driver_code: driver, compound: "MEDIUM", stint, sample_count: 10, stint_length: 10, caveats: [] };
}

const FITS = [fit("ANT", 1), fit("ANT", 2), fit("HAM", 1), fit("RUS", 1), fit("RUS", 2), fit("RUS", 3)];

test("stint fits follow the drivers on screen", () => {
  const fits = tyreFitsFor(FITS, ["ANT", "RUS"], 9);

  assert.deepEqual(
    fits.shown.map((row) => `${row.driver_code}${row.stint}`),
    ["ANT1", "ANT2", "RUS1", "RUS2", "RUS3"]
  );
  assert.equal(fits.total, 5);
});

// The second silent cut in the old chart: `rows.slice(0, 6)` with no count.
test("a cut list of stint fits still reports how many there are", () => {
  const fits = tyreFitsFor(FITS, ["ANT", "HAM", "RUS"], 4);

  assert.equal(fits.shown.length, 4);
  assert.equal(fits.total, 6);
});

test("no drivers on screen means no stint fits", () => {
  assert.deepEqual(tyreFitsFor(FITS, [], 9), { shown: [], total: 0 });
});
