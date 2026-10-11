import assert from "node:assert/strict";
import test from "node:test";

import { driversWithRepeatingFeeds } from "../src/lib/published/coverage.ts";

const shortfall = (bar, driver, detail = "") => ({ bar, driver, detail });

test("a session whose feeds repeated themselves names the drivers, each once and in the pointer's order", () => {
  const coverage = {
    complete: false,
    shortfalls: [
      shortfall("tyre_data", "ALO"),
      shortfall("car_data_repeats", "RUS"),
      shortfall("car_data_repeats", "ANT"),
      shortfall("position_repeats", "RUS"),
      shortfall("position_repeats", "HAD")
    ]
  };

  assert.deepEqual(driversWithRepeatingFeeds(coverage), ["RUS", "ANT", "HAD"]);
});

test("a session short of something else, or of nothing, names none", () => {
  const short = { complete: false, shortfalls: [shortfall("car_data", "RUS"), shortfall("pit_stop_series", null)] };

  assert.deepEqual(driversWithRepeatingFeeds(short), []);
  assert.deepEqual(driversWithRepeatingFeeds({ complete: true, shortfalls: [] }), []);
});
