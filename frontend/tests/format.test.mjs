import assert from "node:assert/strict";
import test from "node:test";

import { formatMs, sessionWhen } from "../src/lib/format.ts";

// What an independent reading of the view modules found (2026-10-07): these
// two had no test, and each printed something untrue for a value that is
// published, or that an average can take.

test("a lap time is rounded to the thousandth before it is split into minutes and seconds", () => {
  assert.equal(formatMs(75521.2), "1:15.521");
  assert.equal(formatMs(72000), "1:12.000");
  // An average half a millisecond short of two minutes was "1:60.000".
  assert.equal(formatMs(119999.6), "2:00.000");
  assert.equal(formatMs(59999.9), "1:00.000");
  assert.equal(formatMs(119999.4), "1:59.999");
  assert.equal(formatMs(3599999.7), "60:00.000");
  assert.equal(formatMs(0), "0:00.000");
  assert.equal(formatMs(-500), "-0:00.500");
  assert.equal(formatMs(-0.2), "0:00.000");
  assert.equal(formatMs(null), "--");
  assert.equal(formatMs(Number.NaN), "--");
});

// The 2026 Australian GP started at 04:00 UTC on 8 March: the afternoon of the
// 8th in Melbourne, and still the 7th in the Americas. The heading of its page
// read "Mar 7, 2026 · Melbourne, Australia" there, a day off from the meeting's
// own date and with nothing to say whose day it was.
test("the heading of a session says when it started with the zone it is told in", () => {
  const started = "2026-03-08T04:00:00Z";
  assert.equal(sessionWhen(started, "America/New_York"), "Mar 7, 2026, 11:00 PM EST");
  assert.equal(sessionWhen(started, "Australia/Melbourne"), "Mar 8, 2026, 3:00 PM GMT+11");
  assert.equal(sessionWhen(started, "UTC"), "Mar 8, 2026, 4:00 AM UTC");
});

test("a session the calendar has only a day for is given that day, wherever it is read", () => {
  // Read as a moment, a day is the evening before to anyone west of Greenwich.
  for (const zone of ["America/Los_Angeles", "UTC", "Asia/Tokyo"]) {
    assert.equal(sessionWhen("2027-03-07", zone), "Mar 7, 2027", zone);
  }
  assert.equal(sessionWhen(null), "TBC");
  assert.equal(sessionWhen("not a time"), "TBC");
});
