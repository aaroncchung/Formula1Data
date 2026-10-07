import assert from "node:assert/strict";
import test from "node:test";

import { calendarDay, sessionStart } from "../src/lib/format.ts";
import { parseSessionAddress } from "../src/lib/published/lookup.ts";
import {
  isUnderPath,
  meetingChoice,
  meetingHref,
  meetingQuery,
  roundParam,
  seasonHref,
  sessionChoice,
  sessionSummaryHref,
  standingsHref,
  yearParam
} from "../src/lib/routes.ts";

const query = (text) => new URLSearchParams(text);

test("every link names what it shows in the query string", () => {
  assert.equal(seasonHref(2026), "/season?year=2026");
  assert.equal(meetingHref(2026, { meeting_key: 1288, round: 8 }), "/meeting?key=1288");
  assert.equal(standingsHref(2026), "/standings?year=2026");
  assert.equal(sessionSummaryHref("/strategy", 11315), "/strategy?key=11315");
});

test("a summary page names its session by key, as the session page does, and by nothing that can change", () => {
  const href = sessionSummaryHref("/telemetry", 11315);

  assert.deepEqual([...new URL(href, "https://site.example").searchParams.keys()], ["key"]);
  assert.deepEqual(parseSessionAddress(new URL(href, "https://site.example").searchParams), {
    kind: "key",
    sessionKey: 11315
  });
});

// AR-20: a round is where a meeting sits in today's calendar. A link that
// carried one opened another weekend once a race was inserted ahead of it.
test("a meeting is linked by its key, and by its round only while it has no key", () => {
  assert.equal(meetingHref(2026, { meeting_key: 1288, round: 8 }), "/meeting?key=1288");
  // The round is not in the link at all, so nothing of it can go stale.
  assert.equal(meetingHref(2026, { meeting_key: 1288, round: 9 }), "/meeting?key=1288");
  // None of its sessions is published, so the index has no key for it yet.
  assert.equal(meetingHref(2026, { meeting_key: null, round: 17 }), "/meeting?year=2026&round=17");
});

test("a meeting's address is read as a key, or as a year and a round", () => {
  assert.deepEqual(meetingChoice(query("key=1288")), { kind: "named", address: { kind: "key", meetingKey: 1288 } });
  assert.deepEqual(meetingChoice(query("year=2026&round=8")), {
    kind: "named",
    address: { kind: "round", year: 2026, round: 8 }
  });
  // The key wins over a round given beside it, which may be out of date.
  assert.deepEqual(meetingChoice(query("key=1288&year=2026&round=9")).address, { kind: "key", meetingKey: 1288 });
  // A key that is not one does not hide a year and round that are well formed.
  assert.deepEqual(meetingChoice(query("key=abc&year=2026&round=8")).address, { kind: "round", year: 2026, round: 8 });
});

test("an address that names no meeting is told apart from one that names it wrongly", () => {
  assert.deepEqual(meetingChoice(query("")), { kind: "none" });
  assert.deepEqual(meetingChoice(query("key=")), { kind: "none" });
  assert.deepEqual(meetingChoice(query("tab=results")), { kind: "none" });
  for (const text of ["key=abc", "key=1.5", "key=-3", "year=2026", "round=8", "year=26&round=8", "year=2026&round=x"]) {
    assert.deepEqual(meetingChoice(query(text)), { kind: "invalid" }, text);
  }
});

test("a meeting's link is read back as the address it was built from", () => {
  for (const address of [
    { kind: "key", meetingKey: 1288 },
    { kind: "round", year: 2026, round: 17 }
  ]) {
    assert.deepEqual(meetingChoice(query(meetingQuery(address))), { kind: "named", address });
  }
});

test("a link that was built is read back as the same values", () => {
  const meetingQuery = new URL(meetingHref(2026, { meeting_key: null, round: 16 }), "https://site.example").searchParams;
  assert.deepEqual(yearParam(meetingQuery), { status: "ok", value: 2026 });
  assert.deepEqual(roundParam(meetingQuery), { status: "ok", value: 16 });

  const sessionQuery = new URL(sessionSummaryHref("/drivers", 11315), "https://site.example").searchParams;
  assert.deepEqual(sessionChoice(sessionQuery), { kind: "named", address: { kind: "key", sessionKey: 11315 } });
});

test("a parameter that is not there is absent, and an empty one is too", () => {
  assert.deepEqual(yearParam(query("")), { status: "absent" });
  assert.deepEqual(yearParam(query("year=")), { status: "absent" });
  assert.deepEqual(roundParam(query("year=2026")), { status: "absent" });
});

test("a mistyped parameter is invalid, not absent, so it is not answered with the default", () => {
  assert.deepEqual(yearParam(query("year=26")), { status: "invalid", raw: "26" });
  assert.deepEqual(yearParam(query("year=2026x")), { status: "invalid", raw: "2026x" });
  assert.deepEqual(roundParam(query("round=-1")), { status: "invalid", raw: "-1" });
  assert.deepEqual(roundParam(query("round=123")), { status: "invalid", raw: "123" });
});

test("a summary page with no session in its address shows the most recent one", () => {
  assert.deepEqual(sessionChoice(query("")), { kind: "latest" });
  // Parameters that are not about a session, and empty ones, name none.
  assert.deepEqual(sessionChoice(query("tab=pace")), { kind: "latest" });
  assert.deepEqual(sessionChoice(query("key=")), { kind: "latest" });
});

test("a summary page reads a session as the session page does, by key or by year, round and type", () => {
  assert.deepEqual(sessionChoice(query("key=11315")), {
    kind: "named",
    address: { kind: "key", sessionKey: 11315 }
  });
  assert.deepEqual(sessionChoice(query("year=2026&round=8&session=r")), {
    kind: "named",
    address: { kind: "route", route: { year: 2026, round: 8, sessionType: "R" } }
  });
  // The key wins over a round given beside it.
  assert.deepEqual(sessionChoice(query("key=11315&year=2026&round=9&session=R")).address, {
    kind: "key",
    sessionKey: 11315
  });
});

test("an address that names a session wrongly is invalid, not a request for the latest", () => {
  for (const text of ["key=abc", "key=1.5", "key=1e3", "key=12345678901234567890", "year=2026", "year=2026&round=8", "session=R"]) {
    assert.deepEqual(sessionChoice(query(text)), { kind: "invalid" }, text);
  }
});

test("a navigation entry is active on its own path and the paths under it", () => {
  assert.equal(isUnderPath("/seasons", ["/seasons"]), true);
  assert.equal(isUnderPath("/seasons/", ["/seasons"]), true);
  assert.equal(isUnderPath("/season/", ["/seasons", "/season", "/meeting", "/session"]), true);
  assert.equal(isUnderPath("/session/", ["/seasons", "/season", "/meeting", "/session"]), true);
  assert.equal(isUnderPath("/standings/", ["/seasons", "/season", "/meeting", "/session"]), false);
  // `/season` is not under `/seasons`, nor the other way round.
  assert.equal(isUnderPath("/season/", ["/seasons"]), false);
  assert.equal(isUnderPath("/seasons/", ["/season"]), false);
});

test("home is active only at home", () => {
  assert.equal(isUnderPath("/", ["/"]), true);
  assert.equal(isUnderPath("/strategy/", ["/"]), false);
});

test("a calendar day is the same day in every time zone", () => {
  // Read as a moment, 2026-06-28 is still the 27th in the Americas.
  assert.equal(calendarDay("2026-06-28"), "Jun 28, 2026");
  assert.equal(calendarDay(null), "TBC");
  assert.equal(calendarDay("not a date"), "TBC");
});

test("a session start names the time zone it is shown in", () => {
  assert.equal(sessionStart("2026-06-28T13:00:00Z", "UTC"), "Sun, Jun 28, 1:00 PM UTC");
  assert.equal(sessionStart("2026-06-28T13:00:00Z", "America/New_York"), "Sun, Jun 28, 9:00 AM EDT");
  assert.equal(sessionStart(null), "Time to be confirmed");
});
