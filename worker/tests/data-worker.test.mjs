import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import worker from "../src/data.mjs";

// The bucket exactly as the publisher writes one. tests/test_contract_fixture.py
// fails when the publisher stops producing this file byte for byte, so the
// Worker is tested against what is really published, not against a guess.
const PUBLISHED = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/published-v1.json", import.meta.url), "utf8")
);
const SESSION_KEY = 11315;

// A stand-in for the R2 binding that does what R2 does where this Worker
// depends on it: `head` returns metadata only, a `get` whose `onlyIf` fails
// returns metadata without a body, and every `get` reports the range it
// returned, the whole object included.
function bucketOf(objects) {
  const calls = [];
  const stored = new Map(
    Object.entries(objects).map(([key, text], index) => [
      key,
      { bytes: new TextEncoder().encode(text), httpEtag: `"etag-${index}"` }
    ])
  );
  // Uploaded part-way through a second, as real objects are.
  const metadata = (object) => ({
    size: object.bytes.byteLength,
    httpEtag: object.httpEtag,
    uploaded: new Date("2026-10-05T20:00:00.789Z"),
    writeHttpMetadata() {}
  });
  return {
    calls,
    stored,
    async head(key) {
      calls.push(`head ${key}`);
      const object = stored.get(key);
      return object ? metadata(object) : null;
    },
    async get(key, options) {
      calls.push(`get ${key}`);
      const object = stored.get(key);
      if (!object) {
        return null;
      }
      if (options?.onlyIf?.get("if-none-match") === object.httpEtag) {
        return metadata(object);
      }
      const asked = /^bytes=(\d+)-(\d+)$/.exec(options?.range?.get("range") || "");
      const range = asked
        ? { offset: Number(asked[1]), length: Number(asked[2]) - Number(asked[1]) + 1 }
        : { offset: 0, length: object.bytes.byteLength };
      return {
        ...metadata(object),
        range,
        body: new Blob([object.bytes.subarray(range.offset, range.offset + range.length)]).stream()
      };
    }
  };
}

function fetchFrom(bucket, path, init) {
  return worker.fetch(new Request(`https://data.example${path}`, init), { ARTIFACTS_BUCKET: bucket });
}

test("a session is read the way a page reads it: pointer once, then generation paths", async () => {
  const bucket = bucketOf(PUBLISHED);

  const index = await (await fetchFrom(bucket, "/data/v1/index.json")).json();
  const race = index.seasons[0].meetings[0].sessions.find((session) => session.type === "R");
  assert.equal(race.session_key, SESSION_KEY);

  const pointerResponse = await fetchFrom(bucket, `/data/v1/pointers/${race.session_key}.json`);
  assert.equal(pointerResponse.status, 200);
  assert.equal(pointerResponse.headers.get("cache-control"), "public, max-age=30, stale-while-revalidate=120");
  const pointer = await pointerResponse.json();

  const base = `/data/v1/generations/${pointer.session_key}/${pointer.generation}`;
  const manifestResponse = await fetchFrom(bucket, `${base}/manifest.json`);
  assert.equal(manifestResponse.status, 200);
  assert.equal(manifestResponse.headers.get("cache-control"), "public, max-age=31536000, immutable");
  const manifest = await manifestResponse.json();
  assert.equal(manifest.schema_version, pointer.format_version);

  bucket.calls.length = 0;
  for (const file of manifest.files) {
    const response = await fetchFrom(bucket, `${base}/${file.path}`);
    assert.equal(response.status, 200, file.path);
    assert.equal(response.headers.get("content-length"), String(file.size_bytes));
    assert.equal((await response.arrayBuffer()).byteLength, file.size_bytes);
  }
  // The Worker read what it was asked for and resolved nothing: no pointer reads.
  assert.deepEqual(
    bucket.calls,
    manifest.files.map((file) => `get v1/generations/${pointer.session_key}/${pointer.generation}/${file.path}`)
  );
});

test("every response may be read from any origin, errors included", async () => {
  const bucket = bucketOf(PUBLISHED);

  for (const path of ["/data/v1/index.json", "/data/v1/pointers/1.json", "/data/archive/x", "/nowhere", "/health"]) {
    const response = await fetchFrom(bucket, path, { headers: { origin: "https://rewrite-data-plane.formula1data.pages.dev" } });
    assert.equal(response.headers.get("access-control-allow-origin"), "*", path);
  }
  const preflight = await fetchFrom(bucket, "/data/v1/index.json", { method: "OPTIONS" });
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get("access-control-allow-methods"), "GET, HEAD, OPTIONS");
});

test("the source archive and the old layout do not exist here", async () => {
  const bucket = bucketOf({
    ...PUBLISHED,
    "archive/sessions/11315/20261005T200000Z-aaaaaaaa/snapshot.json": "{}",
    "catalog.json": "{}",
    "sessions/2026-08-r/summary.json": "{}"
  });

  for (const path of [
    "/data/archive/sessions/11315/20261005T200000Z-aaaaaaaa/snapshot.json",
    "/data/catalog.json",
    "/data/sessions/2026-08-r/summary.json",
    "/data/v1/pointers/999.json",
    "/api/session-status"
  ]) {
    const response = await fetchFrom(bucket, path);
    assert.equal(response.status, 404, path);
  }
  // Nothing outside the versioned layout was even looked up.
  assert.deepEqual(bucket.calls, ["get v1/pointers/999.json"]);
});

test("it only reads", async () => {
  const bucket = bucketOf(PUBLISHED);

  for (const method of ["POST", "PUT", "DELETE", "PATCH"]) {
    const response = await fetchFrom(bucket, "/data/v1/index.json", { method });
    assert.equal(response.status, 405, method);
    assert.equal(response.headers.get("allow"), "GET, HEAD, OPTIONS");
  }
  assert.deepEqual(bucket.calls, []);
});

test("a plain GET is a 200 with no content-range, and revalidation is a 304", async () => {
  const bucket = bucketOf(PUBLISHED);

  const first = await fetchFrom(bucket, "/data/v1/index.json");
  assert.equal(first.status, 200);
  assert.equal(first.headers.get("content-range"), null);

  const again = await fetchFrom(bucket, "/data/v1/index.json", {
    headers: { "if-none-match": first.headers.get("etag") }
  });
  assert.equal(again.status, 304);
  assert.equal(await again.text(), "");
});

test("HEAD returns the headers and reads no body", async () => {
  const bucket = bucketOf(PUBLISHED);

  const response = await fetchFrom(bucket, "/data/v1/index.json", { method: "HEAD" });

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-length"), String(PUBLISHED["v1/index.json"].length));
  assert.deepEqual(bucket.calls, ["head v1/index.json"]);
});

test("an encoded traversal is refused before anything is read", async () => {
  const bucket = bucketOf(PUBLISHED);

  const response = await fetchFrom(bucket, "/data/v1/..%2Farchive/x");

  assert.equal(response.status, 400);
  assert.equal((await response.json()).code, "invalid_artifact_path");
  assert.deepEqual(bucket.calls, []);
});

test("a deployment without its bucket is a fault, not an empty site", async () => {
  const response = await worker.fetch(new Request("https://data.example/data/v1/index.json"), {});

  assert.equal(response.status, 500);
  assert.equal((await response.json()).code, "worker_error");
  assert.equal(response.headers.get("access-control-allow-origin"), "*");
});

test("health answers without the bucket", async () => {
  const response = await worker.fetch(new Request("https://data.example/health"), {});

  assert.deepEqual(await response.json(), { status: "ok", service: "formula-1-data-read" });
});

// --- found in review (GPT-6.1 Sol, 2026-10-06) --------------------------------

function generationPath() {
  const pointer = JSON.parse(PUBLISHED[`v1/pointers/${SESSION_KEY}.json`]);
  return `/data/v1/generations/${pointer.session_key}/${pointer.generation}/summary.json`;
}

test("a failed precondition is not cacheable, even for a path that is immutable", async () => {
  const bucket = bucketOf(PUBLISHED);

  const response = await fetchFrom(bucket, generationPath(), {
    method: "HEAD",
    headers: { "if-match": '"some-other-version"' }
  });

  assert.equal(response.status, 412);
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("a missing artifact is not remembered by a cache", async () => {
  const bucket = bucketOf(PUBLISHED);

  for (const path of ["/data/v1/pointers/999.json", "/data/archive/x", "/nowhere"]) {
    const response = await fetchFrom(bucket, path);
    assert.equal(response.status, 404, path);
    assert.equal(response.headers.get("cache-control"), "no-store", path);
  }
});

test("If-Match compares strongly, If-None-Match weakly", async () => {
  const bucket = bucketOf(PUBLISHED);
  const etag = (await fetchFrom(bucket, "/data/v1/index.json", { method: "HEAD" })).headers.get("etag");

  const strong = await fetchFrom(bucket, "/data/v1/index.json", { method: "HEAD", headers: { "if-match": etag } });
  const weak = await fetchFrom(bucket, "/data/v1/index.json", { method: "HEAD", headers: { "if-match": `W/${etag}` } });
  const any = await fetchFrom(bucket, "/data/v1/index.json", { method: "HEAD", headers: { "if-match": "*" } });
  const revalidation = await fetchFrom(bucket, "/data/v1/index.json", {
    method: "HEAD",
    headers: { "if-none-match": `W/${etag}` }
  });

  assert.deepEqual([strong.status, weak.status, any.status, revalidation.status], [200, 412, 200, 304]);
});

test("the Last-Modified this Worker sends is accepted back as not modified", async () => {
  // The object was uploaded at 20:00:00.789 and Last-Modified says 20:00:00.
  const bucket = bucketOf(PUBLISHED);
  const lastModified = (await fetchFrom(bucket, "/data/v1/index.json", { method: "HEAD" })).headers.get("last-modified");
  assert.equal(lastModified, "Mon, 05 Oct 2026 20:00:00 GMT");

  const since = await fetchFrom(bucket, "/data/v1/index.json", {
    method: "HEAD",
    headers: { "if-modified-since": lastModified }
  });
  const unmodified = await fetchFrom(bucket, "/data/v1/index.json", {
    method: "HEAD",
    headers: { "if-unmodified-since": lastModified }
  });

  assert.deepEqual([since.status, unmodified.status], [304, 200]);
});

test("a range is honoured only while the object is the version the client holds", async () => {
  const bucket = bucketOf(PUBLISHED);
  const whole = PUBLISHED["v1/index.json"];
  const etag = (await fetchFrom(bucket, "/data/v1/index.json", { method: "HEAD" })).headers.get("etag");

  const same = await fetchFrom(bucket, "/data/v1/index.json", {
    headers: { range: "bytes=2-5", "if-range": etag }
  });
  assert.equal(same.status, 206);
  assert.equal(same.headers.get("content-range"), `bytes 2-5/${whole.length}`);
  assert.equal(await same.text(), whole.slice(2, 6));

  // The index was republished since the client fetched its first part.
  const stale = await fetchFrom(bucket, "/data/v1/index.json", {
    headers: { range: "bytes=2-5", "if-range": '"the-version-before"' }
  });
  assert.equal(stale.status, 200);
  assert.equal(stale.headers.get("content-range"), null);
  assert.equal(await stale.text(), whole);

  const weak = await fetchFrom(bucket, "/data/v1/index.json", {
    headers: { range: "bytes=2-5", "if-range": `W/${etag}` }
  });
  assert.equal(weak.status, 200);

  const plain = await fetchFrom(bucket, "/data/v1/index.json", { headers: { range: "bytes=2-5" } });
  assert.equal(plain.status, 206);
});
