import assert from "node:assert/strict";
import test from "node:test";

import {
  findSessionByKey,
  headingOfEntry,
  parseSessionAddress,
  sessionHref,
  sessionQuery
} from "../src/lib/published/lookup.ts";
import { loadAddress, loadSession, loadSessionByKey, recoverSession } from "../src/lib/published/session.ts";

import {
  AUSTRIAN_RACE,
  bucketOf,
  clientOf,
  edit,
  FIRST_GENERATION,
  generationPrefix,
  INDEX_KEY,
  POINTER_KEY,
  removeGeneration,
  republish,
  SESSION_KEY
} from "./support/published-bucket.mjs";

// ---------------------------------------------------------------------------
// Addressing a session by its key
// ---------------------------------------------------------------------------

const address = (query) => parseSessionAddress(new URLSearchParams(query));

test("a query string names a session by its key or by year, round and type", () => {
  assert.deepEqual(address("key=11315"), { kind: "key", sessionKey: 11315 });
  assert.deepEqual(address("year=2026&round=8&session=r"), { kind: "route", route: AUSTRIAN_RACE });
});

// The key is identity; a round beside it may be from before the calendar moved.
test("a key wins over a round given with it", () => {
  assert.deepEqual(address("year=2026&round=9&session=R&key=11315"), { kind: "key", sessionKey: 11315 });
});

test("a key that is not a key does not hide a route that is well formed", () => {
  for (const key of ["", "abc", "-1", "1.5", "11315x", "1e3", "9999999999999"]) {
    assert.deepEqual(address(`key=${key}&year=2026&round=8&session=R`), { kind: "route", route: AUSTRIAN_RACE }, key);
    assert.equal(address(`key=${key}`), null, key);
  }
  assert.equal(address(""), null);
});

test("an address is written the way it is read back", () => {
  for (const query of ["key=11315", "key=0", "year=2026&round=8&session=R", "year=2026&round=16&session=FP1"]) {
    assert.equal(sessionQuery(address(query)), query);
    assert.deepEqual(address(sessionQuery(address(query))), address(query));
  }
  // One spelling for each session: case and leading zeros are not kept.
  assert.equal(sessionQuery(address("session=sq&round=08&year=2026")), "year=2026&round=8&session=SQ");
  assert.equal(sessionQuery(address("key=011315")), "key=11315");
});

test("the link to a session carries its key", () => {
  assert.equal(sessionHref({ kind: "key", sessionKey: 11315 }), "/session?key=11315");
  assert.equal(sessionHref({ kind: "route", route: AUSTRIAN_RACE }), "/session?year=2026&round=8&session=R");
});

test("a key is found where the index places it", async () => {
  const index = await clientOf(bucketOf()).index();

  const place = findSessionByKey(index, SESSION_KEY);
  assert.equal(place.kind, "calendar");
  assert.equal(place.entry.year, 2026);
  assert.equal(place.entry.meeting.round, 8);
  assert.equal(place.entry.session.type, "R");
  assert.equal(findSessionByKey(index, 99999), null);
});

test("a session loads by its key with the round the calendar gives it today", async () => {
  const bucket = bucketOf();

  const loaded = await loadSessionByKey(clientOf(bucket), SESSION_KEY);

  assert.equal(loaded.status, "ready");
  assert.equal(loaded.recovered, false);
  assert.equal(loaded.view.pointer.session_key, SESSION_KEY);
  assert.equal(loaded.view.pointer.generation, FIRST_GENERATION);
  assert.equal(loaded.entry.meeting.name, "Austrian Grand Prix");
  assert.deepEqual(loaded.heading, {
    year: 2026,
    round: 8,
    meetingName: "Austrian Grand Prix",
    sessionName: "Race",
    startTimeUtc: "2026-06-28T13:00:00Z",
    location: null,
    country: null,
    placement: "calendar"
  });
  assert.deepEqual(bucket.keys(), [INDEX_KEY, POINTER_KEY, `${generationPrefix(FIRST_GENERATION)}manifest.json`]);
});

test("the two ways of naming a session load the same thing", async () => {
  const client = clientOf(bucketOf());

  const byKey = await loadAddress(client, { kind: "key", sessionKey: SESSION_KEY });
  const byRoute = await loadAddress(client, { kind: "route", route: AUSTRIAN_RACE });

  assert.equal(byKey.status, "ready");
  assert.equal(byRoute.status, "ready");
  assert.deepEqual(byKey.heading, byRoute.heading);
  assert.deepEqual(byKey.entry, byRoute.entry);
  assert.equal(byKey.view.pointer.generation, byRoute.view.pointer.generation);
});

// AR-20: on 2026-10-05 a race was added and every later round moved by one.
test("a key still names the same session after its round has moved, and the old round does not", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  edit(bucket, INDEX_KEY, (index) => {
    const meetings = index.seasons[0].meetings;
    for (const meeting of meetings) {
      meeting.round += 1;
    }
    meetings.unshift({
      round: 8,
      name: "Madrid Grand Prix",
      official_name: null,
      country: null,
      location: null,
      date: "2026-06-14",
      format: "conventional",
      sessions: [{ type: "R", name: "Race", start_time_utc: "2026-06-14T13:00:00Z" }]
    });
  });

  const byKey = await loadSessionByKey(client, SESSION_KEY);
  assert.equal(byKey.status, "ready");
  assert.equal(byKey.heading.meetingName, "Austrian Grand Prix");
  assert.equal(byKey.heading.round, 9);
  assert.equal(byKey.view.pointer.generation, FIRST_GENERATION);

  const byOldRound = await loadSession(client, AUSTRIAN_RACE);
  assert.equal(byOldRound.status, "unpublished");
  assert.equal(byOldRound.heading.meetingName, "Madrid Grand Prix");
});

/** Move the fixture's session out of the calendar and into the index's `unscheduled` list. */
function unschedule(bucket) {
  edit(bucket, INDEX_KEY, (index) => {
    const race = index.seasons[0].meetings[0].sessions[1];
    delete race.session_key;
    delete race.complete;
    index.unscheduled.push({
      session_key: SESSION_KEY,
      year: 2026,
      type: "R",
      name: "Race",
      meeting_name: "Austrian Grand Prix",
      start_time_utc: "2026-06-28T13:00:00Z",
      complete: true
    });
  });
}

// A published session the calendar has no entry for has no round, so nothing
// but its key can name it.
test("a session outside the calendar opens by its key and has no round", async () => {
  const bucket = bucketOf();
  unschedule(bucket);
  const client = clientOf(bucket);

  const place = findSessionByKey(await client.index(), SESSION_KEY);
  assert.equal(place.kind, "unscheduled");
  assert.equal(place.session.meeting_name, "Austrian Grand Prix");

  const loaded = await loadSessionByKey(client, SESSION_KEY);
  assert.equal(loaded.status, "ready");
  assert.equal(loaded.entry, null);
  assert.deepEqual(loaded.heading, {
    year: 2026,
    round: null,
    meetingName: "Austrian Grand Prix",
    sessionName: "Race",
    startTimeUtc: "2026-06-28T13:00:00Z",
    location: null,
    country: null,
    placement: "unscheduled"
  });
  assert.equal((await loaded.view.read("results.json")).length, 2);

  // The round that used to name it now names a session that is not published.
  assert.equal((await loadSession(client, AUSTRIAN_RACE)).status, "unpublished");
});

// The index is derived after the pointer is written and is cached on its own.
test("a session the index does not list yet opens by its key, introduced by its own pointer", async () => {
  const bucket = bucketOf();
  edit(bucket, INDEX_KEY, (index) => {
    delete index.seasons[0].meetings[0].sessions[1].session_key;
    delete index.seasons[0].meetings[0].sessions[1].complete;
  });

  const loaded = await loadSessionByKey(clientOf(bucket), SESSION_KEY);

  assert.equal(loaded.status, "ready");
  assert.equal(loaded.entry, null);
  assert.equal(loaded.heading.placement, "unplaced");
  assert.equal(loaded.heading.round, null);
  assert.equal(loaded.heading.meetingName, loaded.view.pointer.identity.meeting_name);
  assert.equal(loaded.heading.sessionName, "Race");
  assert.equal(loaded.heading.startTimeUtc, loaded.view.pointer.identity.start_time_utc);
});

test("a key opens its session while the index cannot be read", async () => {
  const bucket = bucketOf();
  bucket.fault = (key) => (key === INDEX_KEY ? new Response("Service Unavailable", { status: 503 }) : undefined);
  const client = clientOf(bucket);

  const byKey = await loadSessionByKey(client, SESSION_KEY);
  assert.equal(byKey.status, "ready");
  assert.equal(byKey.heading.placement, "unplaced");
  assert.equal((await byKey.view.read("results.json")).length, 2);

  // A route has nothing but the index to go on.
  const byRoute = await loadSession(client, AUSTRIAN_RACE);
  assert.equal(byRoute.status, "failed");
  assert.equal(byRoute.failure.code, "unavailable");
});

test("a key nothing is published under is unknown, not an error", async () => {
  const bucket = bucketOf();

  assert.deepEqual(await loadSessionByKey(clientOf(bucket), 99999), { status: "unknown", missing: "key" });
  assert.deepEqual(bucket.keys(), [INDEX_KEY, "v1/pointers/99999.json"]);
});

test("a key the calendar lists whose pointer is absent is 'not published'", async () => {
  const bucket = bucketOf();
  bucket.stored.delete(POINTER_KEY);

  const loaded = await loadSessionByKey(clientOf(bucket), SESSION_KEY);

  assert.equal(loaded.status, "unpublished");
  assert.equal(loaded.entry.session.session_key, SESSION_KEY);
  assert.equal(loaded.heading.round, 8);
});

test("a key whose pointer is broken fails under the heading the calendar gives it", async () => {
  const bucket = bucketOf();
  bucket.stored.set(POINTER_KEY, "<html>Bad gateway</html>");

  const loaded = await loadSessionByKey(clientOf(bucket), SESSION_KEY);

  assert.equal(loaded.status, "failed");
  assert.equal(loaded.failure.code, "invalid_pointer");
  assert.equal(loaded.heading.meetingName, "Austrian Grand Prix");
});

test("a session opened by key outside the calendar recovers without one", async () => {
  const bucket = bucketOf();
  unschedule(bucket);
  const client = clientOf(bucket);
  const loaded = await loadSessionByKey(client, SESSION_KEY);
  const secondGeneration = republish(bucket, { "results.json": [] });
  removeGeneration(bucket, FIRST_GENERATION);

  const recovered = await recoverSession(client, loaded);

  assert.equal(recovered.status, "ready");
  assert.equal(recovered.recovered, true);
  assert.equal(recovered.entry, null);
  assert.deepEqual(recovered.heading, loaded.heading);
  assert.equal(recovered.view.pointer.generation, secondGeneration);

  // Unpublished altogether while open: there is no calendar entry to fall
  // back on, so nothing is left that the key names.
  removeGeneration(bucket, secondGeneration);
  bucket.stored.delete(POINTER_KEY);
  assert.deepEqual(await recoverSession(client, loaded), { status: "unknown", missing: "key" });
});

test("a heading takes the meeting's date when the session has no start time", async () => {
  const index = await clientOf(bucketOf()).index();
  const { entry } = findSessionByKey(index, SESSION_KEY);

  assert.equal(headingOfEntry(entry).startTimeUtc, "2026-06-28T13:00:00Z");
  assert.equal(headingOfEntry({ ...entry, session: { ...entry.session, start_time_utc: null } }).startTimeUtc, "2026-06-27");
});
