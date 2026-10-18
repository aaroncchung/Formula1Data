import assert from "node:assert/strict";
import test from "node:test";

import { driversWithRepeatingFeeds, shortfallGroups } from "../src/lib/published/coverage.ts";

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

// The 2026 Hungarian GP is short of three bars, two of them for nearly the
// whole field, and the banner above every tab had a line for each of its 44
// shortfalls.
test("shortfalls are grouped by bar, each saying who fell short of it", () => {
  const coverage = {
    complete: false,
    shortfalls: [
      shortfall("car_data_repeats", "ALB", "62 of 68 laps"),
      shortfall("car_data_repeats", "ALO", "63 of 69 laps"),
      shortfall("tyre_data", "PER", "23 of 48 expected laps usable"),
      shortfall("car_data_repeats", "ALO", "a second note"),
      shortfall("circuit_info", null, "corner positions did not arrive"),
      shortfall("position", null, "the feed stops in lap 5"),
      shortfall("position", "ALB", "4 of 78 expected laps usable"),
      shortfall("position", "ALO", "3 of 78 expected laps usable")
    ]
  };

  const groups = shortfallGroups(coverage);

  assert.deepEqual(
    groups.map((group) => [group.title, group.who, group.entries.length]),
    [
      ["car data repeats", "2 drivers", 3],
      ["tyre data", "PER", 1],
      ["circuit info", "Whole session", 1],
      ["position", "Whole session and 2 drivers", 3]
    ]
  );
  // Nothing is lost on the way: each shortfall is under its bar, in the pointer's order.
  assert.deepEqual(
    groups[0].entries.map((entry) => entry.detail),
    ["62 of 68 laps", "63 of 69 laps", "a second note"]
  );
  assert.equal(groups.flatMap((group) => group.entries).length, coverage.shortfalls.length);
});

test("a session short of nothing has no groups", () => {
  assert.deepEqual(shortfallGroups({ complete: true, shortfalls: [] }), []);
  assert.deepEqual(
    shortfallGroups({ complete: false, shortfalls: [shortfall("position", null), shortfall("position", "VER")] }).map(
      (group) => group.who
    ),
    ["Whole session and 1 driver"]
  );
});
