import assert from "node:assert/strict";
import test from "node:test";

import { formatResultGap, leaderLapCount } from "../src/lib/results-view.ts";

function result(position, driver, gap, laps, status = "Finished") {
  return { session_id: "2026-08-r", position, driver_code: driver, gap, laps, status };
}

// Rows of the published 2026 Austrian GP classification, as they are stored.
const AUSTRIA = [
  result(1, "RUS", "0 days 01:26:37.979000", 71),
  result(2, "VER", "0 days 00:00:01.611000", 71),
  result(8, "LEC", "0 days 00:00:45.659000", 71),
  result(9, "LAW", "0 days 00:00:15.334000", 70, "Lapped"),
  result(14, "BEA", "0 days 00:01:02.677000", 70, "Lapped"),
  result(18, "ALO", "0 days 00:00:04.833000", 68, "Lapped"),
  result(19, "STR", null, 45, "Retired")
];

const shown = (rows) => rows.map((row) => formatResultGap(row, leaderLapCount(rows)));

test("the winner's entry is the race time, and the rest are gaps to it", () => {
  const [winner, second, , , , , retired] = shown(AUSTRIA);

  assert.equal(winner, "1:26:37.979");
  assert.equal(second, "+1.611s");
  assert.equal(retired, "--");
});

// The stored time of a lapped driver is how long after the winner they took
// the flag. Shown as a gap it puts ninth place 30 seconds ahead of eighth.
test("a lapped driver is shown as laps down, not as the time the artifact stores", () => {
  const [, , leclerc, lawson, bearman, alonso] = shown(AUSTRIA);

  assert.equal(leclerc, "+45.659s");
  assert.equal(lawson, "+1 lap");
  assert.equal(bearman, "+1 lap");
  assert.equal(alonso, "+3 laps");
});

test("a gap of a minute or more is written as minutes and seconds", () => {
  const rows = [result(1, "RUS", "0 days 01:26:37.979000", 71), result(2, "BEA", "0 days 00:01:02.677000", 71)];

  assert.equal(shown(rows)[1], "+1:02.677");
});

test("a retirement short of laps is not called laps down", () => {
  const rows = [result(1, "RUS", "0 days 01:26:37.979000", 71), result(20, "SAI", null, 23, "Retired")];

  assert.equal(shown(rows)[1], "--");
});

test("a lapped driver whose time is missing is still laps down when the status says so", () => {
  const rows = [result(1, "RUS", "0 days 01:26:37.979000", 71), result(9, "LAW", "NaT", 70, "+1 Lap")];

  assert.equal(shown(rows)[1], "+1 lap");
});

test("pandas' words for no value are not printed", () => {
  const rows = [result(1, "RUS", "NaT", 71), result(2, "VER", "NaT", 71), result(3, "ANT", "None", 71), result(4, "PIA", "", 71)];

  assert.deepEqual(shown(rows), ["Winner", "--", "--", "--"]);
});

test("a gap in a form that is not a duration is passed on as written", () => {
  const rows = [result(1, "RUS", "0 days 01:26:37.979000", null), result(2, "VER", "+1 Lap", null)];

  assert.equal(shown(rows)[1], "+1 Lap");
});

test("without lap counts every timed driver is shown by time", () => {
  const rows = AUSTRIA.map((row) => ({ ...row, laps: null }));

  assert.equal(leaderLapCount(rows), null);
  assert.equal(shown(rows)[3], "+15.334s");
});

test("the leader's lap count is the winner's, and absent without a winner", () => {
  assert.equal(leaderLapCount(AUSTRIA), 71);
  assert.equal(leaderLapCount(AUSTRIA.slice(1)), null);
  assert.equal(leaderLapCount([]), null);
});
