import assert from "node:assert/strict";
import test from "node:test";

import { racePaceChartRows } from "../src/lib/race-pace-view.ts";

/** A race-pace row as the analysis writes it. */
function row(driver, gap, lapCount) {
  return {
    driver_code: driver,
    team: "Team",
    lap_count: lapCount,
    median_lap_ms: 75000 + (gap ?? 3000),
    trimmed_mean_lap_ms: 75000,
    fastest_clean_lap_ms: 74000,
    gap_to_best_ms: gap,
    stint: null
  };
}

test("the chart ranks only the drivers with a gap, and names the others", () => {
  // 2025 Mexico: LAW ran one clean lap, and its median of 3.02 s off was a
  // full tank's, not his pace.
  const rows = [row("NOR", 0, 64), row("LEC", 412, 63), row("LAW", null, 1)];

  const { ranked, unranked } = racePaceChartRows(rows);

  assert.deepEqual(
    ranked.map((item) => item.driver_code),
    ["NOR", "LEC"]
  );
  assert.deepEqual(unranked, ["LAW"]);
});

test("a gap of nought is ranked", () => {
  const { ranked, unranked } = racePaceChartRows([row("NOR", 0, 64)]);

  assert.equal(ranked.length, 1);
  assert.deepEqual(unranked, []);
});
