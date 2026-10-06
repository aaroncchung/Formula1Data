import assert from "node:assert/strict";
import test from "node:test";

import {
  clockTimeOfTimestamp,
  formatDuration,
  formatElapsed,
  formatSessionClock,
  formatSessionClockMinutes,
  parsePandasDuration
} from "../src/lib/pandas-time.ts";

// The strings below are the ones in the published 2026 Austrian GP race:
// a pit stop's `local_time`, a weather sample's `timestamp`, a result's `gap`.
test("a pandas duration is read to the millisecond", () => {
  assert.equal(parsePandasDuration("0 days 01:22:52.191000"), 4_972_191);
  assert.equal(parsePandasDuration("0 days 00:00:38.376000"), 38_376);
  assert.equal(parsePandasDuration("0 days 01:26:37.979000"), 5_197_979);
  assert.equal(parsePandasDuration("0 days 00:00:01.611000"), 1_611);
});

test("a duration without a fraction, with days, or with nanoseconds is read too", () => {
  assert.equal(parsePandasDuration("0 days 00:05:00"), 300_000);
  assert.equal(parsePandasDuration("1 days 00:00:01"), 86_401_000);
  assert.equal(parsePandasDuration("2 days 03:04:05.5"), 2 * 86_400_000 + 11_045_500);
  assert.equal(parsePandasDuration("0 days 00:00:00.123456789"), 123);
  assert.equal(parsePandasDuration("  0 days 00:00:02.500000  "), 2_500);
  // The bare clock form, for a source that leaves the day count out.
  assert.equal(parsePandasDuration("01:02:03.250"), 3_723_250);
});

// pandas writes a negative duration as a negative day count and a positive
// clock: minus one and a half seconds is a day back and 23:59:58.5 forward.
test("a negative duration is read as negative", () => {
  assert.equal(parsePandasDuration("-1 days +23:59:58.500000"), -1_500);
  assert.equal(parsePandasDuration("-1 days +00:00:00"), -86_400_000);
});

test("what is not a duration reads as no time, never as zero", () => {
  for (const text of ["NaT", "", "   ", "None", "21.552", "2026-06-28 12:20:00", "0 days", "0 days 1:2:3", "abc"]) {
    assert.equal(parsePandasDuration(text), null, JSON.stringify(text));
  }
  assert.equal(parsePandasDuration(null), null);
  assert.equal(parsePandasDuration(undefined), null);
  assert.equal(parsePandasDuration(4_972_191), null);
});

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

test("the time of day is taken from a pandas timestamp and from nothing else", () => {
  assert.equal(clockTimeOfTimestamp("2026-06-28 12:20:00"), "12:20:00");
  assert.equal(clockTimeOfTimestamp("2026-06-28T14:31:42.123000"), "14:31:42");
  assert.equal(clockTimeOfTimestamp("0 days 01:22:52.191000"), null);
  assert.equal(clockTimeOfTimestamp("12:20:00"), null);
  assert.equal(clockTimeOfTimestamp(""), null);
  assert.equal(clockTimeOfTimestamp(null), null);
});
