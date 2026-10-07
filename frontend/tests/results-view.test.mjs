import assert from "node:assert/strict";
import test from "node:test";

import { readResults } from "../src/lib/published/artifacts.ts";
import {
  classifiedPlace,
  gridLabel,
  isProvisional,
  pointsLabel,
  resultPosition,
  resultTime
} from "../src/lib/results-view.ts";
import { bucketOf, clientOf, SESSION_KEY } from "./support/published-bucket.mjs";

/** A classification row in the published shape; `fields` are the ones a case is about. */
function result(position, driver, fields = {}) {
  return {
    position,
    classified_position: position === null ? null : String(position),
    driver_code: driver,
    time_ms: null,
    gap_ms: null,
    laps_down: null,
    behind_at_flag_ms: null,
    grid: position,
    laps: 71,
    points: 0,
    status: "Finished",
    provisional: false,
    ...fields
  };
}

// The 2026 Austrian GP, as format 2 publishes it. Lawson took the flag 15.3 s
// after the winner and a lap down; Leclerc finished ahead of him, 45.7 s
// behind on the winner's lap.
const AUSTRIA = [
  result(1, "RUS", { time_ms: 5_197_979, points: 25 }),
  result(2, "VER", { gap_ms: 1_611, points: 18 }),
  result(8, "LEC", { gap_ms: 45_659, points: 4 }),
  result(9, "LAW", { laps_down: 1, behind_at_flag_ms: 15_334, laps: 70, status: "Lapped", points: 2 }),
  result(14, "BEA", { laps_down: 1, behind_at_flag_ms: 62_677, laps: 70, status: "Lapped" }),
  result(18, "ALO", { laps_down: 3, behind_at_flag_ms: 4_833, laps: 68, status: "Lapped" }),
  result(19, "STR", { classified_position: "R", laps: 45, status: "Retired" })
];

const times = (rows) => rows.map((row) => resultTime(row).text);

test("the winner's entry is the race time, and a car on the winner's lap has a gap to it", () => {
  const [winner, second, leclerc] = times(AUSTRIA);

  assert.equal(winner, "1:26:37.979");
  assert.equal(second, "+1.611s");
  assert.equal(leclerc, "+45.659s");
});

test("a gap of a minute or more is written as minutes and seconds", () => {
  assert.equal(resultTime(result(2, "BEA", { gap_ms: 62_677 })).text, "+1:02.677");
});

test("a car that took the flag a lap or more behind is shown as laps down", () => {
  const [, , , lawson, bearman, alonso] = times(AUSTRIA);

  assert.equal(lawson, "+1 lap");
  assert.equal(bearman, "+1 lap");
  assert.equal(alonso, "+3 laps");
});

// Shown as a gap, it would put ninth place half a minute ahead of eighth.
test("how long after the winner a lapped car took the flag is beside its laps down, never in their place", () => {
  const lawson = resultTime(AUSTRIA[3]);

  assert.equal(lawson.text, "+1 lap");
  assert.match(lawson.note, /Took the flag 15\.334s after the winner, 1 lap down/);
  assert.match(lawson.note, /not a gap/);
  assert.equal(resultTime(result(9, "LAW", { laps_down: 2 })).note, null);
});

test("a driver with neither a time, a gap nor laps down has no entry", () => {
  const retired = resultTime(AUSTRIA[6]);

  assert.deepEqual(retired, { text: "--", note: null });
  // Laps short of the winner's are not laps down unless the format says so:
  // a retirement is also short of laps.
  assert.equal(resultTime(result(20, "SAI", { laps: 23, status: "Retired" })).text, "--");
});

test("the position is the classification's own, a number or its letter", () => {
  assert.deepEqual(resultPosition(AUSTRIA[0]), { text: "1", note: null });
  assert.deepEqual(resultPosition(AUSTRIA[6]), { text: "R", note: "Retired" });
  assert.deepEqual(resultPosition(result(20, "HUL", { classified_position: "D" })), { text: "D", note: "Disqualified" });
  assert.deepEqual(resultPosition(result(20, "HUL", { classified_position: "X" })), { text: "X", note: null });
  assert.equal(classifiedPlace(AUSTRIA[3]), 9);
  assert.equal(classifiedPlace(AUSTRIA[6]), null);
});

test("a driver the classification leaves out has no position, and the row says so", () => {
  const left = result(null, "DOO", { grid: null, laps: null, points: null, status: null });

  assert.equal(classifiedPlace(left), null);
  assert.equal(resultPosition(left).text, "--");
  assert.match(resultPosition(left).note, /not in the classification/);
});

test("a provisional order is placed by the timing, and is said to be provisional", () => {
  const rows = [
    result(1, "RUS", { classified_position: null, provisional: true, grid: null, points: null, status: null }),
    result(2, "VER", { classified_position: null, provisional: true, grid: null, points: null, status: null })
  ];

  assert.equal(isProvisional(rows), true);
  assert.equal(isProvisional(AUSTRIA), false);
  assert.equal(isProvisional([]), false);
  assert.deepEqual(rows.map((row) => resultPosition(row).text), ["1", "2"]);
  assert.deepEqual(rows.map((row) => pointsLabel(row.points)), ["--", "--"]);
  assert.deepEqual(rows.map((row) => gridLabel(row.grid)), ["--", "--"]);
});

test("no points published is not zero points, and place 0 on the grid is the pit lane", () => {
  assert.equal(pointsLabel(null), "--");
  assert.equal(pointsLabel(0), "0");
  assert.equal(pointsLabel(12.5), "12.5");
  assert.equal(gridLabel(0), "Pit lane");
  assert.equal(gridLabel(5), "5");
  assert.equal(gridLabel(null), "--");
});

test("the classification the publisher writes reads as a race time and a gap", async () => {
  const view = await clientOf(bucketOf()).openSession(SESSION_KEY);

  const { results } = await readResults(view);

  assert.deepEqual(results.map((row) => [resultPosition(row).text, row.driver_code, resultTime(row).text]), [
    ["1", "RUS", "1:26:37.979"],
    ["2", "VER", "+1.611s"]
  ]);
});
