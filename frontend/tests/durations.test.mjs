import assert from "node:assert/strict";
import test from "node:test";

import { formatDuration, formatElapsed, formatSessionClock, formatSessionClockMinutes } from "../src/lib/durations.ts";

// The figures are from the published 2026 Austrian GP race: a pit entry on
// the session clock, a weather sample's time, the winner's race time, a gap.
test("the session clock is shown in hours, minutes and seconds", () => {
  assert.equal(formatSessionClock(4_972_191), "1:22:52");
  assert.equal(formatSessionClock(38_376), "0:00:38");
  assert.equal(formatSessionClock(0), "0:00:00");
  assert.equal(formatSessionClock(-1_500), "-0:00:01");
  assert.equal(formatSessionClock(null), "--");
  assert.equal(formatSessionClock(undefined), "--");
  assert.equal(formatSessionClock(Number.NaN), "--");
});

test("an axis shows the session clock to the minute", () => {
  assert.equal(formatSessionClockMinutes(0), "0:00");
  assert.equal(formatSessionClockMinutes(5 * 60_000), "0:05");
  assert.equal(formatSessionClockMinutes(90 * 60_000), "1:30");
  assert.equal(formatSessionClockMinutes(null), "--");
});

test("a length of time is shown to the millisecond in the shortest form that fits", () => {
  assert.equal(formatDuration(21_552), "21.552");
  assert.equal(formatDuration(1_611), "1.611");
  assert.equal(formatDuration(62_677), "1:02.677");
  assert.equal(formatDuration(5_197_979), "1:26:37.979");
  assert.equal(formatDuration(3_600_000), "1:00:00.000");
  assert.equal(formatDuration(-1_500), "-1.500");
  assert.equal(formatDuration(null), "--");
});

test("seconds get their unit and a time with a colon does not need one", () => {
  assert.equal(formatElapsed(21_552), "21.552s");
  assert.equal(formatElapsed(410_846), "6:50.846");
  assert.equal(formatElapsed(null), "--");
});
