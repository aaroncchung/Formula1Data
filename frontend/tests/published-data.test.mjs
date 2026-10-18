import assert from "node:assert/strict";
import test from "node:test";

import { readLapTimes, readResults } from "../src/lib/published/artifacts.ts";
import { createPublishedClient } from "../src/lib/published/client.ts";
import { FORMAT_VERSION } from "../src/lib/published/config.ts";
import { findSession, isPublished, parseSessionRoute } from "../src/lib/published/lookup.ts";
import { loadSession, notifyWhenGone, recoverSession } from "../src/lib/published/session.ts";

// The stand-in bucket, and the fixture it is filled from, are shared with the
// other tests that read through it.
import {
  AUSTRIAN_RACE,
  BASE_URL,
  bucketOf,
  clientOf,
  dumpJson,
  edit,
  failureOf,
  FIRST_GENERATION,
  generationPrefix,
  INDEX_KEY,
  POINTER_KEY,
  PUBLISHED,
  removeGeneration,
  republish,
  reversedResults,
  SESSION_KEY
} from "./support/published-bucket.mjs";

// ---------------------------------------------------------------------------
// The contract
// ---------------------------------------------------------------------------

test("the published fixture is read the way a page reads it", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);

  const index = await client.index();
  const lookup = findSession(index, AUSTRIAN_RACE);
  assert.equal(lookup.found, true);
  const view = await client.openSession(lookup.entry.session.session_key);

  assert.equal(view.pointer.session_key, SESSION_KEY);
  assert.equal(view.pointer.generation, FIRST_GENERATION);
  assert.equal(view.pointer.format_version, FORMAT_VERSION);
  assert.equal(view.manifest.format_version, FORMAT_VERSION);
  assert.deepEqual(view.pointer.coverage, { complete: true, shortfalls: [] });
  assert.deepEqual(
    view.manifest.files.map((file) => file.path),
    ["analysis/ideal-laps.json", "drivers.json", "results.json", "summary.json", "telemetry/RUS.json", "telemetry/index.json"]
  );
  // The publisher's own bookkeeping is not part of what a page holds.
  assert.equal("also" in view.pointer, false);
  assert.equal("record" in view.pointer, false);
  assert.equal("identity" in view.manifest, false);

  for (const file of view.manifest.files) {
    const stored = PUBLISHED[`${generationPrefix(FIRST_GENERATION)}${file.path}`];
    assert.equal(view.has(file.path), true);
    assert.deepEqual(await view.read(file.path), JSON.parse(stored), file.path);
  }
  assert.deepEqual(bucket.keys(), [
    INDEX_KEY,
    POINTER_KEY,
    `${generationPrefix(FIRST_GENERATION)}manifest.json`,
    ...view.manifest.files.map((file) => `${generationPrefix(FIRST_GENERATION)}${file.path}`)
  ]);
  assert.equal(INDEX_KEY, "v2/index.json");
  assert.equal(POINTER_KEY, "v2/pointers/11315.json");
  assert.ok(generationPrefix(FIRST_GENERATION).startsWith("v2/generations/11315/"));
});

test("a base URL with a trailing slash reads the same keys", async () => {
  const bucket = bucketOf();
  const client = createPublishedClient({ baseUrl: `${BASE_URL}/`, fetch: bucket.fetch });

  await client.index();

  assert.deepEqual(bucket.keys(), [INDEX_KEY]);
});

test("callers that ask for the index at the same moment share one request, and nothing is kept", async () => {
  // A page, the picker above it and a session opened by key all read the
  // calendar as the page loads.
  const bucket = bucketOf();
  const client = clientOf(bucket);

  const [first, second, third] = await Promise.all([client.index(), client.index(), client.index()]);

  assert.equal(bucket.count(INDEX_KEY), 1);
  assert.equal(first, second);
  assert.equal(second, third);

  // The read is forgotten once it settles: the next caller asks again, and
  // the calendar it gets is whatever is published by then.
  edit(bucket, INDEX_KEY, (index) => {
    index.seasons[0].meetings[0].round = 9;
  });
  const later = await client.index();
  assert.equal(bucket.count(INDEX_KEY), 2);
  assert.equal(later.seasons[0].meetings[0].round, 9);
});

test("an index read that fails is not held against the next caller", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  bucket.fault = (key) => (key === INDEX_KEY ? new TypeError("Failed to fetch") : undefined);

  const [first, second] = await Promise.allSettled([client.index(), client.index()]);
  assert.equal(first.status, "rejected");
  assert.equal(second.status, "rejected");
  assert.equal(bucket.count(INDEX_KEY), 1);

  bucket.fault = () => undefined;
  assert.equal((await client.index()).seasons.length, 1);
});

// ---------------------------------------------------------------------------
// Rule 1: a session view reads one generation
// ---------------------------------------------------------------------------

test("the pointer is fetched exactly once however many artifacts are read", async () => {
  const bucket = bucketOf();
  const view = await clientOf(bucket).openSession(SESSION_KEY);

  for (let round = 0; round < 3; round += 1) {
    for (const file of view.manifest.files) {
      await view.read(file.path);
    }
  }

  assert.equal(bucket.count(POINTER_KEY), 1);
  assert.equal(bucket.count(`${generationPrefix(FIRST_GENERATION)}manifest.json`), 1);
  assert.equal(bucket.requests.length, 2 + 3 * view.manifest.files.length);
  for (const key of bucket.keys().slice(1)) {
    assert.ok(key.startsWith(generationPrefix(FIRST_GENERATION)), key);
  }
});

test("an open view keeps reading the generation it pinned after the pointer is replaced", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  const firstResults = JSON.parse(PUBLISHED[`${generationPrefix(FIRST_GENERATION)}results.json`]);

  const open = await client.openSession(SESSION_KEY);
  const secondGeneration = republish(bucket, { "results.json": reversedResults() });
  assert.notEqual(secondGeneration, FIRST_GENERATION);
  bucket.requests.length = 0;

  // The view that was already open: the first generation's bytes, from the
  // first generation's paths, and no second look at the pointer.
  assert.deepEqual(await open.read("results.json"), firstResults);
  await open.read("drivers.json");
  assert.deepEqual(bucket.keys(), [
    `${generationPrefix(FIRST_GENERATION)}results.json`,
    `${generationPrefix(FIRST_GENERATION)}drivers.json`
  ]);
  assert.equal(open.pointer.generation, FIRST_GENERATION);

  // A view opened now: the second generation.
  const fresh = await client.openSession(SESSION_KEY);
  assert.equal(fresh.pointer.generation, secondGeneration);
  assert.equal(fresh.pointer.previous_generation, FIRST_GENERATION);
  assert.deepEqual(await fresh.read("results.json"), reversedResults());

  // And the first one is still where it was, with both open side by side.
  assert.deepEqual(await open.read("results.json"), firstResults);
  assert.equal(bucket.count(POINTER_KEY), 1);
});

test("nothing a caller does to a view changes where it reads from", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  const view = await client.openSession(SESSION_KEY);
  const secondGeneration = republish(bucket, { "results.json": reversedResults() });

  assert.ok(Object.isFrozen(view));
  assert.ok(Object.isFrozen(view.pointer));
  assert.ok(Object.isFrozen(view.manifest));
  assert.ok(Object.isFrozen(view.manifest.files));
  assert.throws(() => {
    view.pointer.generation = secondGeneration;
  }, TypeError);
  assert.throws(() => {
    view.manifest.files.push({ path: "laps.json", size_bytes: 2, sha256: "0".repeat(64) });
  }, TypeError);

  bucket.requests.length = 0;
  await view.read("results.json");
  assert.deepEqual(bucket.keys(), [`${generationPrefix(FIRST_GENERATION)}results.json`]);
});

// ---------------------------------------------------------------------------
// Rule 2: a pinned generation that is gone is reported as that
// ---------------------------------------------------------------------------

test("a 404 on a pinned path is reported as the generation being gone", async () => {
  const bucket = bucketOf();
  const view = await clientOf(bucket).openSession(SESSION_KEY);
  removeGeneration(bucket, FIRST_GENERATION);

  const failure = await failureOf(view.read("results.json"));

  assert.equal(failure.code, "generation_gone");
  assert.equal(failure.details.generation, FIRST_GENERATION);
  assert.equal(failure.details.path, "results.json");
});

test("a pointer whose generation has no manifest is a gone generation, not an unpublished session", async () => {
  const bucket = bucketOf();
  removeGeneration(bucket, FIRST_GENERATION);

  const failure = await failureOf(clientOf(bucket).openSession(SESSION_KEY));

  assert.equal(failure.code, "generation_gone");
});

test("a view tells its holder once that its generation is gone, and only for that", async () => {
  const bucket = bucketOf();
  let told = 0;
  const view = notifyWhenGone(await clientOf(bucket).openSession(SESSION_KEY), () => {
    told += 1;
  });

  // Failures that say nothing about the generation are passed on untouched.
  assert.equal((await failureOf(view.read("laps.json"))).code, "not_in_manifest");
  bucket.fault = () => new Response("busy", { status: 503 });
  assert.equal((await failureOf(view.read("results.json"))).code, "unavailable");
  bucket.fault = () => undefined;
  assert.deepEqual(await view.read("summary.json"), JSON.parse(PUBLISHED[`${generationPrefix(FIRST_GENERATION)}summary.json`]));
  assert.equal(told, 0);

  // A tab reads several files at once and they fail together.
  removeGeneration(bucket, FIRST_GENERATION);
  const failures = await Promise.all([
    failureOf(view.read("results.json")),
    failureOf(view.read("drivers.json")),
    failureOf(view.read("summary.json"))
  ]);

  assert.deepEqual(failures.map((failure) => failure.code), ["generation_gone", "generation_gone", "generation_gone"]);
  assert.equal(told, 1);
  assert.equal(view.pointer.generation, FIRST_GENERATION);
  assert.equal(view.has("results.json"), true);
});

test("a session whose generation is gone is reopened on the new one, once and not in a loop", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  const loaded = await loadSession(client, AUSTRIAN_RACE);
  assert.equal(loaded.status, "ready");
  assert.equal(loaded.recovered, false);

  const secondGeneration = republish(bucket, { "results.json": reversedResults() });
  removeGeneration(bucket, FIRST_GENERATION);
  assert.equal((await failureOf(loaded.view.read("results.json"))).code, "generation_gone");
  bucket.requests.length = 0;

  const recovered = await recoverSession(client, loaded);

  assert.equal(recovered.status, "ready");
  assert.equal(recovered.recovered, true);
  assert.equal(recovered.entry, loaded.entry);
  assert.equal(recovered.view.pointer.generation, secondGeneration);
  assert.deepEqual(await recovered.view.read("results.json"), reversedResults());
  // The pointer was read again, and past the HTTP cache that held the old one.
  assert.deepEqual(bucket.requests, [
    { key: POINTER_KEY, cache: "no-cache" },
    { key: `${generationPrefix(secondGeneration)}manifest.json`, cache: undefined },
    { key: `${generationPrefix(secondGeneration)}results.json`, cache: undefined }
  ]);

  // The second generation goes as well. The page is told, and nothing more is
  // requested: one reload for each load, however often files go missing.
  republish(bucket, { "results.json": [] });
  removeGeneration(bucket, secondGeneration);
  bucket.requests.length = 0;

  const again = await recoverSession(client, recovered);

  assert.equal(again.status, "failed");
  assert.equal(again.failure.code, "generation_gone");
  assert.equal(again.entry, loaded.entry);
  assert.deepEqual(bucket.requests, []);
});

test("a pointer that still names the lost generation is not followed a second time", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  const loaded = await loadSession(client, AUSTRIAN_RACE);
  // The manifest survives, as it does in a browser's cache, so reopening
  // succeeds and would hand back the very generation that is missing files.
  removeGeneration(bucket, FIRST_GENERATION, { keep: ["manifest.json"] });

  const recovered = await recoverSession(client, loaded);

  assert.equal(recovered.status, "failed");
  assert.equal(recovered.failure.code, "generation_gone");
  assert.equal(recovered.failure.details.generation, FIRST_GENERATION);
});

test("a session unpublished while it was open recovers to 'not published'", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  const loaded = await loadSession(client, AUSTRIAN_RACE);
  removeGeneration(bucket, FIRST_GENERATION);
  bucket.stored.delete(POINTER_KEY);

  const recovered = await recoverSession(client, loaded);

  assert.equal(recovered.status, "unpublished");
  assert.equal(recovered.entry, loaded.entry);
});

// ---------------------------------------------------------------------------
// Rule 3: absent is "not published"; present and wrong is an error
// ---------------------------------------------------------------------------

test("an absent pointer means the session is not published", async () => {
  const bucket = bucketOf();
  bucket.stored.delete(POINTER_KEY);

  const failure = await failureOf(clientOf(bucket).openSession(SESSION_KEY));

  assert.equal(failure.code, "not_published");
  assert.deepEqual(bucket.keys(), [POINTER_KEY]);
});

// A publisher before the rule was kept could write one. The index leaves it
// out, and a page opened by the session's key reads the pointer without the
// index.
for (const [type, name] of [["FP2", "Practice 2"], ["Q", "Qualifying"], ["SQ", "Sprint Qualifying"]]) {
  test(`a pointer to a ${name} session is not a published session, by whatever address it is asked for`, async () => {
    const bucket = bucketOf();
    edit(bucket, POINTER_KEY, (pointer) => {
      pointer.identity.session_type = type;
      pointer.identity.session_name = name;
    });

    const failure = await failureOf(clientOf(bucket).openSession(SESSION_KEY));

    assert.equal(failure.code, "not_published");
    assert.match(failure.message, new RegExp(`is a ${name} session, and only races and sprints are published`));
    // Nothing of its generation was asked for.
    assert.deepEqual(bucket.keys(), [POINTER_KEY]);
  });
}

test("a sprint is a published session as a race is", async () => {
  const bucket = bucketOf();
  edit(bucket, POINTER_KEY, (pointer) => {
    pointer.identity.session_type = "S";
    pointer.identity.session_name = "Sprint";
  });

  const view = await clientOf(bucket).openSession(SESSION_KEY);

  assert.equal(view.pointer.identity.session_type, "S");
});

const OTHER_GENERATION = "ab".repeat(32);
const BROKEN_POINTERS = {
  "is not JSON": (bucket) => bucket.stored.set(POINTER_KEY, "<html>Bad gateway</html>"),
  "is cut short": (bucket) => bucket.stored.set(POINTER_KEY, PUBLISHED[POINTER_KEY].slice(0, 200)),
  "is a list": (bucket) => bucket.stored.set(POINTER_KEY, "[]\n"),
  "is null": (bucket) => bucket.stored.set(POINTER_KEY, "null\n"),
  "has another schema_version": (bucket) => edit(bucket, POINTER_KEY, (pointer) => (pointer.schema_version = 2)),
  "has no schema_version": (bucket) => edit(bucket, POINTER_KEY, (pointer) => delete pointer.schema_version),
  "has no format_version": (bucket) => edit(bucket, POINTER_KEY, (pointer) => delete pointer.format_version),
  "names a generation in upper case": (bucket) =>
    edit(bucket, POINTER_KEY, (pointer) => {
      pointer.generation = pointer.generation.toUpperCase();
      pointer.manifest.sha256 = pointer.generation;
    }),
  "names a generation that is too short": (bucket) =>
    edit(bucket, POINTER_KEY, (pointer) => {
      pointer.generation = pointer.generation.slice(0, 40);
      pointer.manifest.sha256 = pointer.generation;
    }),
  "names a generation that is a path": (bucket) =>
    edit(bucket, POINTER_KEY, (pointer) => {
      pointer.generation = "../../pointers";
      pointer.manifest.sha256 = pointer.generation;
    }),
  "names a generation other than its manifest's checksum": (bucket) =>
    edit(bucket, POINTER_KEY, (pointer) => (pointer.generation = OTHER_GENERATION)),
  "has a manifest checksum other than its generation": (bucket) =>
    edit(bucket, POINTER_KEY, (pointer) => (pointer.manifest.sha256 = OTHER_GENERATION)),
  "is the pointer of another session": (bucket) => edit(bucket, POINTER_KEY, (pointer) => (pointer.session_key = 9999)),
  "carries the identity of another session": (bucket) =>
    edit(bucket, POINTER_KEY, (pointer) => (pointer.identity.session_key = 9999)),
  "has a session key that is a string": (bucket) =>
    edit(bucket, POINTER_KEY, (pointer) => (pointer.session_key = String(SESSION_KEY))),
  "has no identity": (bucket) => edit(bucket, POINTER_KEY, (pointer) => delete pointer.identity),
  "has no coverage": (bucket) => edit(bucket, POINTER_KEY, (pointer) => delete pointer.coverage),
  "has a coverage verdict that is not a boolean": (bucket) =>
    edit(bucket, POINTER_KEY, (pointer) => (pointer.coverage.complete = "yes")),
  "has a shortfall without a detail": (bucket) =>
    edit(bucket, POINTER_KEY, (pointer) => (pointer.coverage.shortfalls = [{ bar: "car_data", driver: "VER" }]))
};

for (const [fault, breakPointer] of Object.entries(BROKEN_POINTERS)) {
  test(`a pointer that ${fault} is an error and never "not published"`, async () => {
    const bucket = bucketOf();
    breakPointer(bucket);

    const failure = await failureOf(clientOf(bucket).openSession(SESSION_KEY));

    assert.equal(failure.code, "invalid_pointer", failure.message);
    // Nothing is requested on the strength of a pointer that failed its checks.
    assert.deepEqual(bucket.keys(), [POINTER_KEY]);

    const loaded = await loadSession(clientOf(bucket), AUSTRIAN_RACE);
    assert.equal(loaded.status, "failed");
    assert.equal(loaded.failure.code, "invalid_pointer");
  });
}

test("a pointer is accepted only for the session that was asked for", async () => {
  const bucket = bucketOf();
  bucket.stored.set("v2/pointers/9999.json", PUBLISHED[POINTER_KEY]);

  const failure = await failureOf(clientOf(bucket).openSession(9999));

  assert.equal(failure.code, "invalid_pointer");
  assert.deepEqual(bucket.keys(), ["v2/pointers/9999.json"]);
});

test("a partial session's shortfalls are read from its pointer", async () => {
  const bucket = bucketOf();
  const shortfalls = [
    { bar: "weather", driver: null, detail: "feed did not arrive" },
    { bar: "car_data", driver: "VER", detail: "52 of 71 laps usable" }
  ];
  edit(bucket, POINTER_KEY, (pointer) => (pointer.coverage = { complete: false, shortfalls }));

  const view = await clientOf(bucket).openSession(SESSION_KEY);

  assert.deepEqual(view.pointer.coverage, { complete: false, shortfalls });
});

// ---------------------------------------------------------------------------
// Rule 4: the frontend reads the one format it was built for
// ---------------------------------------------------------------------------

test("a pointer in a later format fails as a version mismatch: the site is older than the data", async () => {
  const bucket = bucketOf();
  edit(bucket, POINTER_KEY, (pointer) => (pointer.format_version = FORMAT_VERSION + 1));

  const failure = await failureOf(clientOf(bucket).openSession(SESSION_KEY));

  assert.equal(failure.code, "format_mismatch");
  assert.deepEqual(failure.details, {
    object: "pointer",
    expected: FORMAT_VERSION,
    found: FORMAT_VERSION + 1,
    site: "older"
  });
  assert.match(failure.message, /older than the data/);
  assert.deepEqual(bucket.keys(), [POINTER_KEY]);
});

test("a pointer in an earlier format fails as a version mismatch: the site is newer than the data", async () => {
  const bucket = bucketOf();
  edit(bucket, POINTER_KEY, (pointer) => (pointer.format_version = FORMAT_VERSION - 1));

  const failure = await failureOf(clientOf(bucket).openSession(SESSION_KEY));

  assert.equal(failure.code, "format_mismatch");
  assert.equal(failure.details.site, "newer");
  assert.match(failure.message, /newer than the data/);
});

test("a pointer in another format is a version mismatch even if the rest of it has changed shape", async () => {
  const bucket = bucketOf();
  bucket.stored.set(
    POINTER_KEY,
    dumpJson({ schema_version: 1, format_version: FORMAT_VERSION + 1, session: { key: SESSION_KEY } })
  );

  const failure = await failureOf(clientOf(bucket).openSession(SESSION_KEY));

  assert.equal(failure.code, "format_mismatch");
});

// What the bucket held under `v1/`, should it ever be served from a `v2/`
// key: each object says it is format 1, and each is refused as that.
test("a format-1 pointer, manifest and index are each refused as the older format they are", async () => {
  const pointer = bucketOf();
  edit(pointer, POINTER_KEY, (value) => {
    value.format_version = 1;
    delete value.also;
    delete value.record;
    delete value.identity.meeting_key;
    delete value.identity.circuit_key;
  });
  const pointerFailure = await failureOf(clientOf(pointer).openSession(SESSION_KEY));
  assert.equal(pointerFailure.code, "format_mismatch");
  assert.deepEqual(pointerFailure.details, { object: "pointer", expected: FORMAT_VERSION, found: 1, site: "newer" });
  assert.match(pointerFailure.message, /newer than the data/);
  assert.deepEqual(pointer.keys(), [POINTER_KEY]);

  // A format-1 manifest gave its format as `schema_version` and had no
  // `format_version` at all, so it is not a manifest this site can read.
  const manifest = bucketOf();
  const manifestKey = `${generationPrefix(FIRST_GENERATION)}manifest.json`;
  edit(manifest, manifestKey, (value) => {
    value.schema_version = 1;
    delete value.format_version;
    delete value.identity;
  });
  const manifestFailure = await failureOf(clientOf(manifest).openSession(SESSION_KEY));
  assert.equal(manifestFailure.code, "invalid_manifest");
  assert.match(manifestFailure.message, /format_version/);

  const index = bucketOf();
  edit(index, INDEX_KEY, (value) => {
    value.format_version = 1;
    for (const meeting of value.seasons[0].meetings) {
      delete meeting.meeting_key;
      delete meeting.circuit_key;
      delete meeting.circuit_name;
      for (const session of meeting.sessions) {
        delete session.in_scope;
      }
    }
  });
  const indexFailure = await failureOf(clientOf(index).index());
  assert.equal(indexFailure.code, "format_mismatch");
  assert.deepEqual(indexFailure.details, { object: "index", expected: FORMAT_VERSION, found: 1, site: "newer" });
  assert.match(indexFailure.message, /newer than the data/);
});

test("a manifest in another format fails the same way, before any artifact is read", async () => {
  const bucket = bucketOf();
  const manifestKey = `${generationPrefix(FIRST_GENERATION)}manifest.json`;
  edit(bucket, manifestKey, (manifest) => (manifest.format_version = FORMAT_VERSION + 1));

  const failure = await failureOf(clientOf(bucket).openSession(SESSION_KEY));

  assert.equal(failure.code, "format_mismatch");
  assert.equal(failure.details.object, "manifest");
  assert.equal(failure.details.site, "older");
  assert.deepEqual(bucket.keys(), [POINTER_KEY, manifestKey]);

  const loaded = await loadSession(clientOf(bucket), AUSTRIAN_RACE);
  assert.equal(loaded.status, "failed");
  assert.equal(loaded.failure.code, "format_mismatch");
  assert.equal(loaded.entry.meeting.name, "Austrian Grand Prix");
});

test("an index in another format fails the same way", async () => {
  const bucket = bucketOf();
  edit(bucket, INDEX_KEY, (index) => (index.format_version = FORMAT_VERSION + 1));

  const failure = await failureOf(clientOf(bucket).index());

  assert.equal(failure.code, "format_mismatch");
  assert.equal(failure.details.object, "index");
});

const BROKEN_MANIFESTS = {
  "is not JSON": (bucket, key) => bucket.stored.set(key, "not json"),
  "belongs to another session": (bucket, key) => edit(bucket, key, (manifest) => (manifest.session_key = 9999)),
  "has no file list": (bucket, key) => edit(bucket, key, (manifest) => delete manifest.files),
  "lists a path outside the generation": (bucket, key) =>
    edit(bucket, key, (manifest) => (manifest.files[0].path = `../../../pointers/${SESSION_KEY}.json`)),
  "lists an absolute path": (bucket, key) => edit(bucket, key, (manifest) => (manifest.files[0].path = "/results.json")),
  "lists a path with a backslash": (bucket, key) =>
    edit(bucket, key, (manifest) => (manifest.files[0].path = "analysis\\..\\..\\x.json")),
  "lists a file without a size": (bucket, key) => edit(bucket, key, (manifest) => delete manifest.files[0].size_bytes)
};

for (const [fault, breakManifest] of Object.entries(BROKEN_MANIFESTS)) {
  test(`a manifest that ${fault} is invalid`, async () => {
    const bucket = bucketOf();
    const manifestKey = `${generationPrefix(FIRST_GENERATION)}manifest.json`;
    breakManifest(bucket, manifestKey);

    const failure = await failureOf(clientOf(bucket).openSession(SESSION_KEY));

    assert.equal(failure.code, "invalid_manifest", failure.message);
    assert.deepEqual(bucket.keys(), [POINTER_KEY, manifestKey]);
  });
}

// ---------------------------------------------------------------------------
// Rule 5: only what the manifest lists is requested
// ---------------------------------------------------------------------------

test("a path the manifest does not list fails without a request", async () => {
  const bucket = bucketOf();
  // Present in the bucket, under the pinned generation, and still not readable:
  // the manifest is what defines the generation, not what happens to be stored.
  bucket.stored.set(`${generationPrefix(FIRST_GENERATION)}laps.json`, "[]\n");
  const view = await clientOf(bucket).openSession(SESSION_KEY);
  bucket.requests.length = 0;

  for (const path of [
    "laps.json",
    "analysis/lap-times.json",
    "manifest.json",
    "",
    "/results.json",
    "results.json?generation=other",
    "./results.json",
    `../../../pointers/${SESSION_KEY}.json`,
    `../${OTHER_GENERATION}/results.json`
  ]) {
    assert.equal(view.has(path), false, path);
    const failure = await failureOf(view.read(path));
    assert.equal(failure.code, "not_in_manifest", path);
  }

  assert.deepEqual(bucket.requests, []);
});

// ---------------------------------------------------------------------------
// Unavailable is not missing
// ---------------------------------------------------------------------------

const OUTAGES = {
  "a network failure": () => new TypeError("fetch failed"),
  "a 500": () => Response.json({ code: "worker_error", message: "Unexpected Worker error" }, { status: 500 }),
  "a 503": () => new Response("Service Unavailable", { status: 503 }),
  "a 403": () => new Response("Forbidden", { status: 403 }),
  "a body that breaks off": () => ({
    status: 200,
    text: async () => {
      throw new TypeError("terminated");
    }
  })
};

for (const [outage, respond] of Object.entries(OUTAGES)) {
  test(`${outage} is reported as unavailable, not as missing`, async () => {
    const bucket = bucketOf();
    const client = clientOf(bucket);
    const manifestKey = `${generationPrefix(FIRST_GENERATION)}manifest.json`;
    const resultsKey = `${generationPrefix(FIRST_GENERATION)}results.json`;
    const failingOn = (broken) => (key) => (key === broken ? respond() : undefined);

    // The index: a failed load, not an empty calendar.
    bucket.fault = failingOn(INDEX_KEY);
    assert.equal((await failureOf(client.index())).code, "unavailable");
    const loaded = await loadSession(client, AUSTRIAN_RACE);
    assert.equal(loaded.status, "failed");
    assert.equal(loaded.failure.code, "unavailable");

    // The pointer: not "not published".
    bucket.fault = failingOn(POINTER_KEY);
    assert.equal((await failureOf(client.openSession(SESSION_KEY))).code, "unavailable");
    const unreachable = await loadSession(client, AUSTRIAN_RACE);
    assert.equal(unreachable.status, "failed");
    assert.equal(unreachable.failure.code, "unavailable");

    // The manifest and an artifact: not "the generation is gone".
    bucket.fault = failingOn(manifestKey);
    assert.equal((await failureOf(client.openSession(SESSION_KEY))).code, "unavailable");
    bucket.fault = () => undefined;
    const view = await client.openSession(SESSION_KEY);
    bucket.fault = failingOn(resultsKey);
    assert.equal((await failureOf(view.read("results.json"))).code, "unavailable");

    // And the view is as good as before once the outage is over.
    bucket.fault = () => undefined;
    assert.equal((await view.read("results.json")).length, 2);
  });
}

test("a request that outlives the timeout is unavailable", async () => {
  // The client's timer does not keep Node alive on its own; a browser tab has
  // no such concern.
  const keepAlive = setTimeout(() => {}, 5_000);
  const client = createPublishedClient({
    baseUrl: BASE_URL,
    timeoutMs: 10,
    fetch: (url, init) =>
      new Promise((resolve, reject) => {
        init.signal.addEventListener("abort", () => reject(init.signal.reason));
      })
  });

  try {
    assert.equal((await failureOf(client.openSession(SESSION_KEY))).code, "unavailable");
  } finally {
    clearTimeout(keepAlive);
  }
});

test("an index that is absent or not an index is told apart from an outage", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);

  bucket.stored.delete(INDEX_KEY);
  assert.equal((await failureOf(client.index())).code, "index_missing");

  bucket.stored.set(INDEX_KEY, "<!doctype html>");
  assert.equal((await failureOf(client.index())).code, "invalid_index");

  bucket.stored.set(
    INDEX_KEY,
    dumpJson({ schema_version: 2, format_version: FORMAT_VERSION, seasons: [], unscheduled: [] })
  );
  assert.equal((await failureOf(client.index())).code, "invalid_index");

  bucket.stored.set(INDEX_KEY, PUBLISHED[INDEX_KEY]);
  edit(bucket, INDEX_KEY, (index) => (index.seasons[0].meetings[0].sessions[1].session_key = "11315"));
  assert.equal((await failureOf(client.index())).code, "invalid_index");

  // Whether a session is one the publisher covers is asked of every session.
  bucket.stored.set(INDEX_KEY, PUBLISHED[INDEX_KEY]);
  edit(bucket, INDEX_KEY, (index) => delete index.seasons[0].meetings[0].sessions[0].in_scope);
  const noScope = await failureOf(client.index());
  assert.equal(noScope.code, "invalid_index");
  assert.match(noScope.message, /in_scope/);

  // A published session says whether it is complete.
  bucket.stored.set(INDEX_KEY, PUBLISHED[INDEX_KEY]);
  edit(bucket, INDEX_KEY, (index) => delete index.seasons[0].meetings[0].sessions[1].complete);
  assert.equal((await failureOf(client.index())).code, "invalid_index");

  bucket.stored.set(INDEX_KEY, PUBLISHED[INDEX_KEY]);
  edit(bucket, INDEX_KEY, (index) => (index.seasons[0].meetings[0].meeting_key = "1315"));
  assert.equal((await failureOf(client.index())).code, "invalid_index");
});

test("an artifact that is not JSON is invalid, not gone", async () => {
  const bucket = bucketOf();
  const view = await clientOf(bucket).openSession(SESSION_KEY);
  bucket.stored.set(`${generationPrefix(FIRST_GENERATION)}results.json`, "<html>");

  assert.equal((await failureOf(view.read("results.json"))).code, "invalid_artifact");
});

test("without a base URL nothing is requested", async () => {
  const bucket = bucketOf();
  const client = createPublishedClient({ baseUrl: "", fetch: bucket.fetch });

  assert.equal((await failureOf(client.index())).code, "not_configured");
  assert.equal((await failureOf(client.openSession(SESSION_KEY))).code, "not_configured");
  assert.deepEqual(bucket.requests, []);
});

// ---------------------------------------------------------------------------
// Rule 5 of the publication rules: the round is looked up, never kept
// ---------------------------------------------------------------------------

test("a route is found in the index by year, round and session type", async () => {
  const index = await clientOf(bucketOf()).index();

  const race = findSession(index, AUSTRIAN_RACE);
  assert.equal(race.found, true);
  assert.equal(race.entry.year, 2026);
  assert.equal(race.entry.meeting.round, 8);
  assert.equal(race.entry.meeting.name, "Austrian Grand Prix");
  assert.equal(race.entry.meeting.meeting_key, 1315);
  assert.deepEqual(race.entry.session, {
    type: "R",
    name: "Race",
    start_time_utc: "2026-06-28T13:00:00Z",
    in_scope: true,
    session_key: SESSION_KEY,
    complete: true
  });
  assert.deepEqual(findSession(index, { year: 2026, round: 8, sessionType: "r" }), race);
});

test("a session that is in the calendar and not published has no key", async () => {
  const index = await clientOf(bucketOf()).index();

  const qualifying = findSession(index, { year: 2026, round: 8, sessionType: "Q" });
  assert.equal(qualifying.found, true);
  assert.equal(isPublished(qualifying.entry.session), false);
  // Neither field is there at all, as the publisher writes it: not null.
  assert.deepEqual(qualifying.entry.session, {
    type: "Q",
    name: "Qualifying",
    start_time_utc: "2026-06-27T14:00:00Z",
    in_scope: false
  });

  // Not published and in scope: a race that has not been run or published
  // yet. Its meeting has no key until one of its sessions is published.
  const monza = findSession(index, { year: 2026, round: 14, sessionType: "R" });
  assert.equal(monza.found, true);
  assert.equal(isPublished(monza.entry.session), false);
  assert.equal(monza.entry.session.in_scope, true);
  assert.equal(monza.entry.meeting.meeting_key, null);
});

test("a year, a round or a session the calendar does not have is told apart", async () => {
  const index = await clientOf(bucketOf()).index();

  assert.deepEqual(findSession(index, { year: 2031, round: 8, sessionType: "R" }), { found: false, missing: "year" });
  assert.deepEqual(findSession(index, { year: 2026, round: 9, sessionType: "R" }), { found: false, missing: "round" });
  assert.deepEqual(findSession(index, { year: 2026, round: 8, sessionType: "S" }), { found: false, missing: "session" });
});

test("the same session is found under a different round after the calendar changes", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);
  const before = await loadSession(client, AUSTRIAN_RACE);
  assert.equal(before.status, "ready");

  // A race is added before Austria, as on 2026-10-05 (AR-20): every later
  // round moves by one. The publisher derives the index again; no pointer and
  // no generation changes.
  edit(bucket, INDEX_KEY, (index) => {
    const meetings = index.seasons[0].meetings;
    for (const meeting of meetings) {
      meeting.round += 1;
    }
    meetings.unshift({
      round: 8,
      meeting_key: null,
      circuit_key: null,
      circuit_name: null,
      name: "Madrid Grand Prix",
      official_name: null,
      country: null,
      location: null,
      date: "2026-06-14",
      format: "conventional",
      sessions: [{ type: "R", name: "Race", start_time_utc: "2026-06-14T13:00:00Z", in_scope: true }]
    });
  });

  const moved = await loadSession(client, { year: 2026, round: 9, sessionType: "R" });
  assert.equal(moved.status, "ready");
  assert.equal(moved.entry.meeting.round, 9);
  assert.equal(moved.entry.meeting.name, "Austrian Grand Prix");
  assert.equal(moved.entry.session.session_key, SESSION_KEY);
  assert.equal(moved.view.pointer.session_key, SESSION_KEY);
  assert.equal(moved.view.pointer.generation, before.view.pointer.generation);

  // The old round now names another race, which has not been published. The
  // view opened before the change is untouched: it never held a round.
  const old = await loadSession(client, AUSTRIAN_RACE);
  assert.equal(old.status, "unpublished");
  assert.equal(old.entry.meeting.name, "Madrid Grand Prix");
  assert.equal((await before.view.read("summary.json")).meeting, "Austrian Grand Prix");
});

test("a query string is a route only when all three parts are well formed", () => {
  const route = (query) => parseSessionRoute(new URLSearchParams(query));

  assert.deepEqual(route("year=2026&round=8&session=R"), AUSTRIAN_RACE);
  assert.deepEqual(route("session=fp1&round=08&year=2026"), { year: 2026, round: 8, sessionType: "FP1" });
  for (const query of [
    "",
    "year=2026&round=8",
    "year=2026&session=R",
    "round=8&session=R",
    "year=26&round=8&session=R",
    "year=2026&round=eight&session=R",
    "year=2026&round=-1&session=R",
    "year=2026&round=8.5&session=R",
    "year=2026&round=8&session=",
    "year=2026&round=8&session=../R"
  ]) {
    assert.equal(route(query), null, query);
  }
});

// ---------------------------------------------------------------------------
// Loading a session for a page
// ---------------------------------------------------------------------------

test("a route loads to a view pinned to the session's current generation", async () => {
  const bucket = bucketOf();

  const loaded = await loadSession(clientOf(bucket), AUSTRIAN_RACE);

  assert.equal(loaded.status, "ready");
  assert.equal(loaded.recovered, false);
  assert.equal(loaded.entry.meeting.name, "Austrian Grand Prix");
  assert.equal(loaded.entry.session.name, "Race");
  assert.equal(loaded.view.pointer.generation, FIRST_GENERATION);
  assert.deepEqual(bucket.requests, [
    { key: INDEX_KEY, cache: undefined },
    { key: POINTER_KEY, cache: undefined },
    { key: `${generationPrefix(FIRST_GENERATION)}manifest.json`, cache: undefined }
  ]);
});

test("a route the calendar does not have loads to 'unknown' without reading a pointer", async () => {
  const bucket = bucketOf();
  const client = clientOf(bucket);

  assert.deepEqual(await loadSession(client, { year: 2031, round: 8, sessionType: "R" }), { status: "unknown", missing: "year" });
  assert.deepEqual(await loadSession(client, { year: 2026, round: 99, sessionType: "R" }), { status: "unknown", missing: "round" });
  assert.deepEqual(await loadSession(client, { year: 2026, round: 8, sessionType: "FP1" }), { status: "unknown", missing: "session" });
  assert.deepEqual(bucket.keys(), [INDEX_KEY, INDEX_KEY, INDEX_KEY]);
});

test("a session in the calendar that is not published loads to 'unpublished' without reading a pointer", async () => {
  const bucket = bucketOf();

  const loaded = await loadSession(clientOf(bucket), { year: 2026, round: 8, sessionType: "Q" });

  assert.equal(loaded.status, "unpublished");
  assert.equal(loaded.entry.meeting.name, "Austrian Grand Prix");
  assert.equal(loaded.entry.session.name, "Qualifying");
  assert.deepEqual(bucket.keys(), [INDEX_KEY]);
});

test("an index that names a session whose pointer is absent loads to 'unpublished' too", async () => {
  const bucket = bucketOf();
  bucket.stored.delete(POINTER_KEY);

  const loaded = await loadSession(clientOf(bucket), AUSTRIAN_RACE);

  assert.equal(loaded.status, "unpublished");
  assert.equal(loaded.entry.session.session_key, SESSION_KEY);
});

// ---------------------------------------------------------------------------
// What a tab reads
// ---------------------------------------------------------------------------

test("each tab reads its own artifacts from the pinned generation, and only those", async () => {
  const bucket = bucketOf();
  const lapTimes = [{ name: "RUS", x: [1, 2], y: [70123, 69874], color: "#27F4D2" }];
  const generation = republish(bucket, { "analysis/lap-times.json": lapTimes });
  const view = await clientOf(bucket).openSession(SESSION_KEY);
  bucket.requests.length = 0;

  const { results, drivers } = await readResults(view);
  assert.deepEqual(results.map((row) => [row.position, row.driver_code, row.points]), [[1, "RUS", 25], [2, "VER", 18]]);
  assert.deepEqual(drivers.map((driver) => [driver.code, driver.team.name]), [["RUS", "Mercedes"], ["VER", "Red Bull"]]);
  assert.deepEqual(bucket.keys().sort(), [`${generationPrefix(generation)}drivers.json`, `${generationPrefix(generation)}results.json`]);

  // The lap-time chart is styled from the driver list, so its tab reads both.
  bucket.requests.length = 0;
  const lapTimeTab = await readLapTimes(view);
  assert.deepEqual(lapTimeTab.series, lapTimes);
  assert.deepEqual(lapTimeTab.drivers, drivers);
  assert.deepEqual(bucket.keys(), [
    `${generationPrefix(generation)}analysis/lap-times.json`,
    `${generationPrefix(generation)}drivers.json`
  ]);
});

test("a tab whose artifact the generation does not hold fails on its own, without a request", async () => {
  const bucket = bucketOf();
  const view = await clientOf(bucket).openSession(SESSION_KEY);
  bucket.requests.length = 0;

  // The fixture's generation has no lap times; its results are still there.
  assert.equal((await failureOf(readLapTimes(view))).code, "not_in_manifest");
  assert.deepEqual(bucket.requests, []);
  assert.equal((await readResults(view)).results.length, 2);
});

test("an artifact that should be a list and is not is invalid", async () => {
  const bucket = bucketOf();
  republish(bucket, { "results.json": { error: "no classification" } });
  const view = await clientOf(bucket).openSession(SESSION_KEY);

  assert.equal((await failureOf(readResults(view))).code, "invalid_artifact");
});
