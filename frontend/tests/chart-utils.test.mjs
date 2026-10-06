import assert from "node:assert/strict";
import test from "node:test";

import { groupByDriver, seriesToRows } from "../src/lib/chart-utils.ts";

test("rows are grouped by driver in order of first appearance", () => {
  const rows = [
    { driver_code: "RUS", stint: 1 },
    { driver_code: "ANT", stint: 1 },
    { driver_code: "RUS", stint: 2 }
  ];

  assert.deepEqual(groupByDriver(rows), [
    ["RUS", [rows[0], rows[2]]],
    ["ANT", [rows[1]]]
  ]);
});

test("grouping nothing yields no groups", () => {
  assert.deepEqual(groupByDriver([]), []);
});

test("series pivot into one row per lap, with a gap where a driver has no lap", () => {
  const rows = seriesToRows([
    { name: "RUS", x: [2, 1, 3], y: [71000, 82000, 70500], metadata: {} },
    { name: "ANT", x: [1, 3], y: [83000, null], metadata: {} }
  ]);

  assert.deepEqual(rows, [
    { lap: 1, RUS: 82000, ANT: 83000 },
    { lap: 2, RUS: 71000, ANT: null },
    { lap: 3, RUS: 70500, ANT: null }
  ]);
});
