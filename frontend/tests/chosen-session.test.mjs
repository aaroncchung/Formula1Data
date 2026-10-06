import assert from "node:assert/strict";
import test from "node:test";

import { findPublishedSession } from "../src/lib/calendar.ts";
import { describeSession, loadChosenSession, recoverChosenSession } from "../src/lib/chosen-session.ts";
import { notifyWhenGone } from "../src/lib/published/session.ts";
import { readField, readStrategy } from "../src/lib/session-summaries.ts";
import {
  bucketOf,
  clientOf,
  edit,
  FIRST_GENERATION as GENERATION,
  generationPrefix,
  INDEX_KEY,
  POINTER_KEY,
  removeGeneration,
  republish,
  reversedResults,
  SESSION_KEY as AUSTRIAN_RACE_KEY
} from "./support/published-bucket.mjs";
import { sampleIndex } from "./support/sample-index.mjs";

const GENERATION_PREFIX = generationPrefix(GENERATION);
const MANIFEST_KEY = `${GENERATION_PREFIX}manifest.json`;

// ---------------------------------------------------------------------------
// Which session a page shows
// ---------------------------------------------------------------------------

test("with no key a page opens the most recent published session", async () => {
  const bucket = bucketOf();

  const load = await loadChosenSession(clientOf(bucket), null);

  assert.equal(load.status, "ready");
  assert.equal(load.key, AUSTRIAN_RACE_KEY);
  assert.equal(load.listing.meetingName, "Austrian Grand Prix");
  assert.equal(load.view.pointer.generation, GENERATION);
  assert.equal(load.recovered, false);
  assert.equal(load.index.seasons.length, 1);
  assert.deepEqual(bucket.keys(), [INDEX_KEY, POINTER_KEY, MANIFEST_KEY]);
});

test("a key opens that session", async () => {
  const bucket = bucketOf();

  const load = await loadChosenSession(clientOf(bucket), AUSTRIAN_RACE_KEY);

  assert.equal(load.status, "ready");
  assert.equal(load.view.pointer.session_key, AUSTRIAN_RACE_KEY);
  assert.deepEqual(bucket.keys(), [INDEX_KEY, POINTER_KEY, MANIFEST_KEY]);
});

test("everything a page reads comes from the generation it pinned", async () => {
  const bucket = bucketOf();
  const load = await loadChosenSession(clientOf(bucket), null);
  assert.equal(load.status, "ready");

  // The session is published again while the page is open.
  const second = republish(bucket, { "results.json": reversedResults() });
  assert.notEqual(second, GENERATION);
  bucket.requests.length = 0;

  const field = await readField(load.view);

  assert.equal(field.results[0].driver_code, "RUS");
  for (const key of bucket.keys()) {
    assert.ok(key.startsWith(GENERATION_PREFIX), key);
  }
  assert.equal(bucket.count(POINTER_KEY), 0);
});

test("a key neither the calendar nor a pointer has is unknown", async () => {
  const bucket = bucketOf();

  const load = await loadChosenSession(clientOf(bucket), 4242);

  assert.deepEqual({ status: load.status, key: load.key }, { status: "unknown", key: 4242 });
  assert.ok(load.index, "the calendar is still there for choosing another session");
  assert.deepEqual(bucket.keys(), [INDEX_KEY, "v1/pointers/4242.json"]);
});

test("a published session the calendar does not list yet is opened from its pointer", async () => {
  // The index is derived after a pointer is written. In between, the session
  // is in the bucket and not in the calendar.
  const bucket = bucketOf();
  edit(bucket, INDEX_KEY, (index) => {
    for (const item of index.seasons[0].meetings[0].sessions) {
      delete item.session_key;
      delete item.complete;
    }
  });

  const load = await loadChosenSession(clientOf(bucket), AUSTRIAN_RACE_KEY);

  assert.equal(load.status, "ready");
  assert.equal(load.listing, null);
  assert.deepEqual(describeSession(load.listing, load.view.pointer.identity), {
    year: 2026,
    round: null,
    meetingName: "Austrian Grand Prix",
    sessionName: "Race",
    startTimeUtc: "2026-06-28T13:00:00Z",
    place: null
  });
});

test("a session the calendar lists whose pointer is absent is unpublished, not broken", async () => {
  const bucket = bucketOf();
  bucket.stored.delete(POINTER_KEY);

  const chosen = await loadChosenSession(clientOf(bucket), AUSTRIAN_RACE_KEY);
  assert.equal(chosen.status, "unpublished");
  assert.equal(chosen.listing.key, AUSTRIAN_RACE_KEY);

  // The same when it was the default and not the reader's choice.
  const latest = await loadChosenSession(clientOf(bucket), null);
  assert.equal(latest.status, "unpublished");
});

test("a calendar with nothing published is its own state, and opens nothing", async () => {
  const bucket = bucketOf();
  edit(bucket, INDEX_KEY, (index) => {
    for (const item of index.seasons[0].meetings[0].sessions) {
      delete item.session_key;
      delete item.complete;
    }
  });

  const load = await loadChosenSession(clientOf(bucket), null);

  assert.equal(load.status, "none_published");
  assert.equal(load.index.seasons[0].meetings.length, 2);
  assert.deepEqual(bucket.keys(), [INDEX_KEY]);
});

// ---------------------------------------------------------------------------
// Failures are told apart
// ---------------------------------------------------------------------------

test("a calendar that cannot be reached is not an empty calendar", async () => {
  const bucket = bucketOf();
  bucket.fault = (key) => (key === INDEX_KEY ? new TypeError("Failed to fetch") : undefined);

  const load = await loadChosenSession(clientOf(bucket), null);

  assert.equal(load.status, "no_calendar");
  assert.equal(load.failure.code, "unavailable");
  assert.deepEqual(bucket.keys(), [INDEX_KEY]);
});

test("a calendar in a format this site does not read says so", async () => {
  const bucket = bucketOf();
  edit(bucket, INDEX_KEY, (index) => {
    index.format_version = 2;
  });

  const load = await loadChosenSession(clientOf(bucket), AUSTRIAN_RACE_KEY);

  assert.equal(load.status, "no_calendar");
  assert.equal(load.failure.code, "format_mismatch");
  assert.equal(load.failure.details.site, "older");
  // The session is not opened on the strength of a calendar that was not read.
  assert.deepEqual(bucket.keys(), [INDEX_KEY]);
});

test("a missing calendar and an invalid one are different failures", async () => {
  const missing = bucketOf();
  missing.stored.delete(INDEX_KEY);
  assert.equal((await loadChosenSession(clientOf(missing), null)).failure.code, "index_missing");

  const invalid = bucketOf();
  invalid.stored.set(INDEX_KEY, "{}");
  assert.equal((await loadChosenSession(clientOf(invalid), null)).failure.code, "invalid_index");
});

test("a pointer that cannot be trusted is a failure of that session, with the calendar kept", async () => {
  const bucket = bucketOf();
  edit(bucket, POINTER_KEY, (pointer) => {
    pointer.generation = "not-a-generation";
  });

  const load = await loadChosenSession(clientOf(bucket), null);

  assert.equal(load.status, "failed");
  assert.equal(load.failure.code, "invalid_pointer");
  assert.equal(load.listing.key, AUSTRIAN_RACE_KEY);
  assert.ok(load.index);
});

test("an outage while opening the session is not shown as unpublished", async () => {
  const bucket = bucketOf();
  bucket.fault = (key) => (key === POINTER_KEY ? new Response("busy", { status: 503 }) : undefined);

  const load = await loadChosenSession(clientOf(bucket), AUSTRIAN_RACE_KEY);

  assert.equal(load.status, "failed");
  assert.equal(load.failure.code, "unavailable");
});

// ---------------------------------------------------------------------------
// The pinned generation goes away
// ---------------------------------------------------------------------------

test("a page whose generation is gone reopens the session on the new one, once", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  const first = await loadChosenSession(client, null);
  assert.equal(first.status, "ready");

  const second = republish(bucket, { "results.json": reversedResults() });
  removeGeneration(bucket, GENERATION);

  // A read through the page's view finds the generation gone and says so.
  let told = 0;
  const watched = notifyWhenGone(first.view, () => {
    told += 1;
  });
  await assert.rejects(() => readField(watched), (error) => error.code === "generation_gone");
  assert.equal(told, 1);

  bucket.requests.length = 0;
  const recovered = await recoverChosenSession(client, first);

  assert.equal(recovered.status, "ready");
  assert.equal(recovered.recovered, true);
  assert.equal(recovered.view.pointer.generation, second);
  assert.equal(recovered.key, AUSTRIAN_RACE_KEY);
  // The pointer is checked with the server, not answered from the cache that
  // named the generation that is gone.
  assert.deepEqual(bucket.requests[0], { key: POINTER_KEY, cache: "no-cache" });
  assert.equal((await readField(recovered.view)).results[0].driver_code, "VER");
});

test("a pointer that still names the missing generation is a failure, not a reload loop", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  const first = await loadChosenSession(client, null);
  removeGeneration(bucket, GENERATION, { keep: ["manifest.json"] });

  const recovered = await recoverChosenSession(client, first);

  assert.equal(recovered.status, "failed");
  assert.equal(recovered.failure.code, "generation_gone");
  assert.match(recovered.failure.message, /still names generation/);
  assert.equal(recovered.listing.key, AUSTRIAN_RACE_KEY);
});

test("a session is reopened at most once for each load", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  const first = await loadChosenSession(client, null);
  republish(bucket, { "results.json": reversedResults() });
  const recovered = await recoverChosenSession(client, first);
  assert.equal(recovered.status, "ready");
  bucket.requests.length = 0;

  const again = await recoverChosenSession(client, recovered);

  assert.equal(again.status, "failed");
  assert.equal(again.failure.code, "generation_gone");
  assert.deepEqual(bucket.keys(), []);
});

// ---------------------------------------------------------------------------
// Describing the session
// ---------------------------------------------------------------------------

test("a session is described from the calendar, and its round is today's", async () => {
  const bucket = bucketOf();
  // The calendar has moved the meeting since the session was fetched: the
  // pointer still records round 8 (`round_at_fetch`), the calendar says 9.
  edit(bucket, INDEX_KEY, (index) => {
    index.seasons[0].meetings[0].round = 9;
    index.seasons[0].meetings[0].location = "Spielberg";
    index.seasons[0].meetings[0].country = "Austria";
  });

  const load = await loadChosenSession(clientOf(bucket), AUSTRIAN_RACE_KEY);

  assert.equal(load.status, "ready");
  assert.deepEqual(describeSession(load.listing, load.view.pointer.identity), {
    year: 2026,
    round: 9,
    meetingName: "Austrian Grand Prix",
    sessionName: "Race",
    startTimeUtc: "2026-06-28T13:00:00Z",
    place: "Spielberg, Austria"
  });
});

test("a session the calendar cannot place has no round, and its place comes from the pointer", () => {
  // The index lists it as published and has no meeting for it, so there is no
  // round to show today. The round the pointer recorded when the session was
  // fetched is not a substitute: it is where the calendar had it then.
  const listing = findPublishedSession(sampleIndex(), 11200);
  const identity = {
    session_key: 11200,
    year: 2026,
    session_type: "R",
    session_name: "Race",
    start_time_utc: "2026-05-17T13:00:00Z",
    meeting_name: "Imola Grand Prix",
    meeting_official_name: null,
    location: "Imola",
    country: "Italy",
    circuit_name: null,
    round_at_fetch: 7
  };

  assert.deepEqual(describeSession(listing, identity), {
    year: 2026,
    round: null,
    meetingName: "Imola Grand Prix",
    sessionName: "Race",
    startTimeUtc: "2026-05-17T13:00:00Z",
    place: "Imola, Italy"
  });
});

test("a session nothing is known about has no description", () => {
  assert.equal(describeSession(null, null), null);
});

test("a file the generation does not hold is absent for the page, not an error", async () => {
  // The fixture's generation holds drivers, results and a summary, and none
  // of what the strategy page reads.
  const bucket = bucketOf();
  const load = await loadChosenSession(clientOf(bucket), null);
  bucket.requests.length = 0;

  assert.deepEqual(await readStrategy(load.view), { stints: null, pitStops: null, strategy: null });
  assert.deepEqual(bucket.keys(), []);
});
