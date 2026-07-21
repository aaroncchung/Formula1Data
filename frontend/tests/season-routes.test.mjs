import assert from "node:assert/strict";
import test from "node:test";

import {
  meetingHref,
  parseExploreTarget,
  seasonHref,
  sessionHref
} from "../src/lib/season-routes.ts";

test("stable explore hrefs cover seasons, meetings, sessions, and fragments", () => {
  assert.equal(seasonHref(2027), "/seasons/explore?year=2027");
  assert.equal(meetingHref(2027, 3), "/seasons/explore?year=2027&round=3");
  assert.equal(
    sessionHref(2027, 3, "sq", "telemetry"),
    "/seasons/explore?year=2027&round=3&session=SQ#telemetry"
  );
});

test("explore query parsing selects the requested view", () => {
  assert.deepEqual(parseExploreTarget(new URLSearchParams("year=2027")), {
    kind: "season",
    year: 2027
  });
  assert.deepEqual(parseExploreTarget(new URLSearchParams("year=2027&round=3")), {
    kind: "meeting",
    year: 2027,
    round: 3
  });
  assert.deepEqual(parseExploreTarget(new URLSearchParams("year=2027&round=3&session=sq")), {
    kind: "session",
    year: 2027,
    round: 3,
    session: "SQ"
  });
});

test("explore query parsing rejects incomplete or invalid routes", () => {
  for (const query of [
    "",
    "year=0",
    "year=2027&session=R",
    "year=2027&round=0",
    "year=2027&round=3&session=Practice"
  ]) {
    assert.equal(parseExploreTarget(new URLSearchParams(query)).kind, "error");
  }
});
