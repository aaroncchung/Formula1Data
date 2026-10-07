import assert from "node:assert/strict";
import test from "node:test";

import {
  describeMeetingCoverage,
  findMeeting,
  findSeason,
  latestPublishedSession,
  meetingCoverage,
  nextSession,
  publishedSessions,
  seasonOverviews,
  sessionAvailability,
  sessionLabel,
  unscheduledSessions,
  venues
} from "../src/lib/calendar.ts";
import { fixtureIndex, indexOf, meeting, NOW, sampleIndex, session } from "./support/sample-index.mjs";

/** One row of the list of published sessions, by its key. */
const listed = (index, key) => publishedSessions(index).find((item) => item.key === key) ?? null;

// ---------------------------------------------------------------------------
// What a page may say about one session
// ---------------------------------------------------------------------------

test("a published session is complete or partial, and never anything else", () => {
  const [barcelona, austria] = findSeason(sampleIndex(), 2026).meetings;

  assert.equal(sessionAvailability(austria.sessions[2], NOW), "complete");
  assert.equal(sessionAvailability(barcelona.sessions[1], NOW), "partial");
  // Whether the session has started is beside the point once it is published.
  assert.equal(sessionAvailability(barcelona.sessions[1], 0), "partial");
});

test("a session the publisher covers is scheduled until it starts and not published afterwards", () => {
  const [, , britain] = findSeason(sampleIndex(), 2026).meetings;
  const race = britain.sessions[1];
  assert.equal(race.in_scope, true);

  assert.equal(sessionAvailability(race, NOW), "scheduled");
  // The moment it starts it has been run, as far as the calendar can tell.
  const start = Date.parse(race.start_time_utc);
  assert.equal(sessionAvailability(race, start - 1), "scheduled");
  assert.equal(sessionAvailability(race, start), "not_published");
});

// The index says of each session whether the publisher takes that kind at
// all. One it does not take is not awaited, however long ago it was run, and
// it is not something still to come either.
test("a session the publisher does not cover is that, before it is run and after", () => {
  const [barcelona, , britain] = findSeason(sampleIndex(), 2026).meetings;
  const run = barcelona.sessions[0];
  const toCome = britain.sessions[0];
  assert.equal(run.in_scope, false);
  assert.equal(toCome.in_scope, false);

  assert.equal(sessionAvailability(run, NOW), "not_covered");
  assert.equal(sessionAvailability(toCome, NOW), "not_covered");
  assert.equal(sessionAvailability(toCome, 0), "not_covered");
});

test("a published session is shown as published even where its kind is marked out of scope", () => {
  const index = indexOf([
    {
      year: 2026,
      meetings: [
        meeting(1, "First", "2026-03-08", [
          session("Q", "Qualifying", "2026-03-07T05:00:00Z", { session_key: 5, complete: true }, false)
        ])
      ]
    }
  ]);

  assert.equal(sessionAvailability(index.seasons[0].meetings[0].sessions[0], NOW), "complete");
});

test("a session the calendar has not timed is scheduled, not missing", () => {
  const index = indexOf([
    { year: 2027, meetings: [meeting(1, "Australian Grand Prix", null, [session("R", "Race", null)])] }
  ]);

  assert.equal(sessionAvailability(index.seasons[0].meetings[0].sessions[0], NOW), "scheduled");
});

// ---------------------------------------------------------------------------
// Published sessions, and which one is the most recent
// ---------------------------------------------------------------------------

test("published sessions are listed newest first, with the ones the calendar cannot place", () => {
  assert.deepEqual(
    publishedSessions(sampleIndex()).map((item) => [item.key, item.meetingName, item.type, item.meeting?.round ?? null]),
    [
      [11315, "Austrian Grand Prix", "R", 8],
      [11314, "Austrian Grand Prix", "S", 8],
      [11300, "Barcelona Grand Prix", "R", 7],
      [11200, "Imola Grand Prix", "R", null],
      [9001, "Abu Dhabi Grand Prix", "R", 24]
    ]
  );
});

test("the most recent published session is the one that started last, whatever its round", () => {
  // The calendar after a race was inserted ahead of an older one: the round
  // numbers no longer follow the dates, and the date is what "recent" means.
  const index = indexOf([
    {
      year: 2026,
      meetings: [
        meeting(3, "Late Grand Prix", "2026-09-06", [
          session("R", "Race", "2026-09-06T13:00:00Z", { session_key: 30, complete: true })
        ]),
        meeting(9, "Early Grand Prix", "2026-04-05", [
          session("R", "Race", "2026-04-05T13:00:00Z", { session_key: 90, complete: true })
        ])
      ]
    }
  ]);

  assert.equal(latestPublishedSession(index).key, 30);
});

test("a published session with no start time is placed by its meeting's date", () => {
  const index = indexOf([
    {
      year: 2026,
      meetings: [
        meeting(1, "First", "2026-03-08", [session("R", "Race", "2026-03-08T04:00:00Z", { session_key: 1, complete: true })]),
        meeting(2, "Second", "2026-03-15", [session("R", "Race", null, { session_key: 2, complete: true })])
      ]
    }
  ]);

  assert.deepEqual(publishedSessions(index).map((item) => item.key), [2, 1]);
});

test("a calendar with nothing published has no most recent session", () => {
  const index = indexOf([
    { year: 2026, meetings: [meeting(1, "First", "2026-03-08", [session("R", "Race", "2026-03-08T04:00:00Z")])] }
  ]);

  assert.deepEqual(publishedSessions(index), []);
  assert.equal(latestPublishedSession(index), null);
});

test("a session is listed under its key, in the calendar or out of it", () => {
  const index = sampleIndex();

  assert.equal(listed(index, 11315).meeting.round, 8);
  assert.equal(listed(index, 11200).meeting, null);
  assert.equal(listed(index, 11200).meetingName, "Imola Grand Prix");
  assert.equal(listed(index, 4), null);
});

test("the same key is listed after the calendar renumbers its round", () => {
  // AR-20: a race is inserted and every later round moves by one. A page that
  // kept the round would now open a different race; the key still names the
  // same one, and the round shown is the new one.
  const before = sampleIndex();
  const after = indexOf([
    {
      year: 2026,
      meetings: [
        meeting(8, "Inserted Grand Prix", "2026-06-21", [session("R", "Race", "2026-06-21T13:00:00Z")]),
        meeting(9, "Austrian Grand Prix", "2026-06-28", [
          session("R", "Race", "2026-06-28T13:00:00Z", { session_key: 11315, complete: true })
        ])
      ]
    }
  ]);

  assert.equal(listed(before, 11315).meeting.round, 8);
  assert.equal(listed(after, 11315).meeting.round, 9);
  assert.equal(listed(after, 11315).meetingName, "Austrian Grand Prix");
});

test("a session is named in one line, saying when it is partial or outside the calendar", () => {
  const index = sampleIndex();

  assert.equal(sessionLabel(listed(index, 11315)), "R8 · Austrian Grand Prix · Race");
  assert.equal(sessionLabel(listed(index, 11314)), "R8 · Austrian Grand Prix · Sprint");
  assert.equal(sessionLabel(listed(index, 11300)), "R7 · Barcelona Grand Prix · Race (partial)");
  assert.equal(sessionLabel(listed(index, 11200)), "Imola Grand Prix · Race · not in the calendar");
});

test("the published fixture's one session is its most recent", () => {
  const latest = latestPublishedSession(fixtureIndex());

  assert.equal(latest.key, 11315);
  assert.equal(latest.complete, true);
  assert.equal(latest.meetingName, "Austrian Grand Prix");
  assert.equal(latest.meeting.round, 8);
});

// ---------------------------------------------------------------------------
// Seasons and meetings
// ---------------------------------------------------------------------------

test("each season is summed up once, the newest first", () => {
  // 2026: seven sessions in the calendar, of which three are qualifying,
  // which is not covered. The four it covers and the one it cannot place
  // make five, and four of those are published.
  assert.deepEqual(seasonOverviews(sampleIndex()), [
    { year: 2026, meetingCount: 3, sessionCount: 7, coveredCount: 5, publishedCount: 4, partialCount: 1, unscheduledCount: 1 },
    { year: 2025, meetingCount: 1, sessionCount: 1, coveredCount: 1, publishedCount: 1, partialCount: 0, unscheduledCount: 0 }
  ]);
});

test("a weekend's coverage counts what the site covers, and names what it does not", () => {
  const [barcelona, austria, britain] = findSeason(sampleIndex(), 2026).meetings;

  assert.deepEqual(meetingCoverage(austria), { published: 2, covered: 2, notCovered: ["Qualifying"] });
  assert.equal(
    describeMeetingCoverage(meetingCoverage(austria)),
    "2 of the 2 sessions this site covers are published. Not covered: Qualifying."
  );
  assert.equal(
    describeMeetingCoverage(meetingCoverage(barcelona)),
    "1 of the 1 session this site covers is published. Not covered: Qualifying."
  );
  // Nothing published is "not yet", and only for what is covered.
  assert.equal(
    describeMeetingCoverage(meetingCoverage(britain)),
    "The one session of this weekend that this site covers is not published yet. Not covered: Qualifying."
  );
});

test("a weekend with nothing the site covers says so, and a fully covered one names nothing", () => {
  const practice = meeting(1, "Test", "2026-02-20", [
    session("FP1", "Practice 1", "2026-02-20T10:00:00Z"),
    session("FP2", "Practice 2", "2026-02-20T14:00:00Z")
  ]);
  const sprint = meeting(2, "Sprint", "2026-03-14", [
    session("S", "Sprint", "2026-03-14T03:00:00Z"),
    session("R", "Race", "2026-03-15T07:00:00Z")
  ]);
  const index = indexOf([{ year: 2026, meetings: [practice, sprint] }]);
  const [first, second] = index.seasons[0].meetings;

  assert.equal(describeMeetingCoverage(meetingCoverage(first)), "None of this weekend's sessions is of a kind this site publishes.");
  assert.equal(
    describeMeetingCoverage(meetingCoverage(second)),
    "None of the 2 sessions of this weekend that this site covers is published yet."
  );
});

test("a year that only has sessions the calendar cannot place is still a season", () => {
  const index = indexOf(
    [],
    [
      {
        session_key: 7,
        year: 2024,
        type: "R",
        name: "Race",
        meeting_name: "Lost Grand Prix",
        start_time_utc: "2024-05-05T13:00:00Z",
        complete: false
      }
    ]
  );

  assert.deepEqual(seasonOverviews(index), [
    { year: 2024, meetingCount: 0, sessionCount: 0, coveredCount: 1, publishedCount: 1, partialCount: 1, unscheduledCount: 1 }
  ]);
  assert.equal(findSeason(index, 2024), null);
  assert.deepEqual(unscheduledSessions(index, 2024).map((item) => item.key), [7]);
});

test("an empty calendar has no seasons, which is not the same as a season with no races", () => {
  assert.deepEqual(seasonOverviews(indexOf([])), []);
  assert.deepEqual(seasonOverviews(indexOf([{ year: 2027, meetings: [] }])), [
    { year: 2027, meetingCount: 0, sessionCount: 0, coveredCount: 0, publishedCount: 0, partialCount: 0, unscheduledCount: 0 }
  ]);
});

test("a meeting is looked up by year and round, with its neighbours", () => {
  const index = sampleIndex();

  const austria = findMeeting(index, 2026, 8);
  assert.equal(austria.found, true);
  assert.equal(austria.meeting.name, "Austrian Grand Prix");
  assert.equal(austria.previous.name, "Barcelona Grand Prix");
  assert.equal(austria.next.name, "British Grand Prix");

  const first = findMeeting(index, 2026, 7);
  assert.equal(first.previous, null);
  assert.equal(findMeeting(index, 2026, 9).next, null);
});

test("a meeting link the calendar does not have says which part is missing", () => {
  const index = sampleIndex();

  assert.deepEqual(findMeeting(index, 2031, 1), { found: false, missing: "year" });
  assert.deepEqual(findMeeting(index, 2026, 30), { found: false, missing: "round" });
});

test("the next session is the first one that has not started", () => {
  const index = sampleIndex();

  const next = nextSession(index, NOW);
  assert.equal(next.meeting.name, "British Grand Prix");
  assert.equal(next.session.type, "Q");
  assert.equal(next.year, 2026);

  assert.equal(nextSession(index, Date.parse("2026-07-04T15:00:00Z")).session.type, "R");
  assert.equal(nextSession(index, Date.parse("2027-01-01T00:00:00Z")), null);
});

// ---------------------------------------------------------------------------
// Venues
// ---------------------------------------------------------------------------

test("meetings are grouped by place across seasons, the most recent first", () => {
  const index = indexOf([
    {
      year: 2025,
      meetings: [
        meeting(11, "Austrian Grand Prix", "2025-06-29", [session("R", "Race", "2025-06-29T13:00:00Z")], {
          country: "Austria",
          location: "Spielberg"
        })
      ]
    },
    {
      year: 2026,
      meetings: [
        meeting(7, "Barcelona Grand Prix", "2026-06-14", [session("R", "Race", "2026-06-14T13:00:00Z")], {
          country: "Spain",
          location: "Barcelona"
        }),
        meeting(
          8,
          "Austrian Grand Prix",
          "2026-06-28",
          [session("R", "Race", "2026-06-28T13:00:00Z", { session_key: 11315, complete: true })],
          { country: "Austria", location: "Spielberg" }
        ),
        meeting(14, "Spanish Grand Prix", "2026-09-13", [session("R", "Race", "2026-09-13T13:00:00Z")], {
          country: "Spain",
          location: "Madrid"
        })
      ]
    }
  ]);

  assert.deepEqual(
    venues(index).map((venue) => [
      venue.place,
      venue.country,
      venue.meetings.map((item) => `${item.year}/${item.meeting.round}`),
      venue.publishedCount
    ]),
    [
      ["Barcelona", "Spain", ["2026/7"], 0],
      ["Madrid", "Spain", ["2026/14"], 0],
      ["Spielberg", "Austria", ["2026/8", "2025/11"], 1]
    ]
  );
});

test("a meeting with no location is a venue under its own name", () => {
  // The published fixture has neither location nor country.
  assert.deepEqual(
    venues(fixtureIndex()).map((venue) => [venue.place, venue.country, venue.publishedCount]),
    [
      ["Austrian Grand Prix", null, 1],
      ["Italian Grand Prix", null, 0]
    ]
  );
});
