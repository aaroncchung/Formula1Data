import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import worker from "../src/data.mjs";

// The bucket exactly as the publisher writes one. tests/test_contract_fixture.py
// fails when the publisher stops producing this file byte for byte, so the
// Worker is tested against what is really published, not against a guess.
const PUBLISHED = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/published-v2.json", import.meta.url), "utf8")
);
const SESSION_KEY = 11315;

// A stand-in for the R2 binding that does what R2 does where this Worker
// depends on it: `head` returns metadata only, a `get` whose `onlyIf` fails
// returns metadata without a body, and every `get` reports the range it
// returned, the whole object included. Given a `Range` header, R2 reads what
// it can of it: it sent the whole object for `bytes=abc`, and threw for a
// range that starts past the end. That is taken to come before `onlyIf`, so
// the Worker's answer may not depend on the order.
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
      const range = rangeOf(options?.range, object.bytes.byteLength);
      if (options?.onlyIf?.get("if-none-match") === object.httpEtag) {
        return metadata(object);
      }
      const { offset, length } =
        "suffix" in range ? { offset: object.bytes.byteLength - range.suffix, length: range.suffix } : range;
      return {
        ...metadata(object),
        range,
        body: new Blob([object.bytes.subarray(offset, offset + length)]).stream()
      };
    }
  };
}

function rangeOf(headers, size) {
  const asked = /^bytes=(\d*)-(\d*)$/.exec(headers?.get("range") || "");
  if (!asked || (asked[1] === "" && asked[2] === "")) {
    return { offset: 0, length: size };
  }
  if (asked[1] === "") {
    return { suffix: Math.min(Number(asked[2]), size) };
  }
  const offset = Number(asked[1]);
  if (offset >= size) {
    throw new Error("get: The requested range is not satisfiable (10039)");
  }
  const last = asked[2] === "" ? size - 1 : Math.min(Number(asked[2]), size - 1);
  return { offset, length: last - offset + 1 };
}

function fetchFrom(bucket, path, init) {
  return worker.fetch(new Request(`https://data.example${path}`, init), { ARTIFACTS_BUCKET: bucket });
}

test("a session is read the way a page reads it: pointer once, then generation paths", async () => {
  const bucket = bucketOf(PUBLISHED);

  const index = await (await fetchFrom(bucket, "/data/v2/index.json")).json();
  const race = index.seasons[0].meetings[0].sessions.find((session) => session.type === "R");
  assert.equal(race.session_key, SESSION_KEY);

  const pointerResponse = await fetchFrom(bucket, `/data/v2/pointers/${race.session_key}.json`);
  assert.equal(pointerResponse.status, 200);
  assert.equal(pointerResponse.headers.get("cache-control"), "public, max-age=30, stale-while-revalidate=120");
  const pointer = await pointerResponse.json();

  const base = `/data/v2/generations/${pointer.session_key}/${pointer.generation}`;
  const manifestResponse = await fetchFrom(bucket, `${base}/manifest.json`);
  assert.equal(manifestResponse.status, 200);
  assert.equal(manifestResponse.headers.get("cache-control"), "public, max-age=31536000, immutable");
  const manifest = await manifestResponse.json();
  assert.equal(manifest.format_version, pointer.format_version);

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
    manifest.files.map((file) => `get v2/generations/${pointer.session_key}/${pointer.generation}/${file.path}`)
  );
});

test("every response may be read from any origin, errors included", async () => {
  const bucket = bucketOf(PUBLISHED);

  for (const path of ["/data/v2/index.json", "/data/v2/pointers/1.json", "/data/archive/x", "/nowhere", "/health"]) {
    const response = await fetchFrom(bucket, path, { headers: { origin: "https://rewrite-data-plane.formula1data.pages.dev" } });
    assert.equal(response.headers.get("access-control-allow-origin"), "*", path);
  }
  const preflight = await fetchFrom(bucket, "/data/v2/index.json", { method: "OPTIONS" });
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
    "/data/v2/pointers/999.json",
    "/api/session-status"
  ]) {
    const response = await fetchFrom(bucket, path);
    assert.equal(response.status, 404, path);
  }
  // Nothing outside the versioned layout was even looked up.
  assert.deepEqual(bucket.calls, ["get v2/pointers/999.json"]);
});

test("it only reads", async () => {
  const bucket = bucketOf(PUBLISHED);

  for (const method of ["POST", "PUT", "DELETE", "PATCH"]) {
    const response = await fetchFrom(bucket, "/data/v2/index.json", { method });
    assert.equal(response.status, 405, method);
    assert.equal(response.headers.get("allow"), "GET, HEAD, OPTIONS");
  }
  assert.deepEqual(bucket.calls, []);
});

test("a plain GET is a 200 with no content-range, and revalidation is a 304", async () => {
  const bucket = bucketOf(PUBLISHED);

  const first = await fetchFrom(bucket, "/data/v2/index.json");
  assert.equal(first.status, 200);
  assert.equal(first.headers.get("content-range"), null);

  const again = await fetchFrom(bucket, "/data/v2/index.json", {
    headers: { "if-none-match": first.headers.get("etag") }
  });
  assert.equal(again.status, 304);
  assert.equal(await again.text(), "");
});

test("HEAD returns the headers and reads no body", async () => {
  const bucket = bucketOf(PUBLISHED);

  const response = await fetchFrom(bucket, "/data/v2/index.json", { method: "HEAD" });

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-length"), String(PUBLISHED["v2/index.json"].length));
  assert.deepEqual(bucket.calls, ["head v2/index.json"]);
});

test("an encoded traversal is refused before anything is read", async () => {
  const bucket = bucketOf(PUBLISHED);

  const response = await fetchFrom(bucket, "/data/v2/..%2Farchive/x");

  assert.equal(response.status, 400);
  assert.equal((await response.json()).code, "invalid_artifact_path");
  assert.deepEqual(bucket.calls, []);
});

test("a deployment without its bucket is a fault, not an empty site", async () => {
  const response = await worker.fetch(new Request("https://data.example/data/v2/index.json"), {});

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
  const pointer = JSON.parse(PUBLISHED[`v2/pointers/${SESSION_KEY}.json`]);
  return `/data/v2/generations/${pointer.session_key}/${pointer.generation}/summary.json`;
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

  for (const path of ["/data/v2/pointers/999.json", "/data/archive/x", "/nowhere"]) {
    const response = await fetchFrom(bucket, path);
    assert.equal(response.status, 404, path);
    assert.equal(response.headers.get("cache-control"), "no-store", path);
  }
});

test("If-Match compares strongly, If-None-Match weakly", async () => {
  const bucket = bucketOf(PUBLISHED);
  const etag = (await fetchFrom(bucket, "/data/v2/index.json", { method: "HEAD" })).headers.get("etag");

  const strong = await fetchFrom(bucket, "/data/v2/index.json", { method: "HEAD", headers: { "if-match": etag } });
  const weak = await fetchFrom(bucket, "/data/v2/index.json", { method: "HEAD", headers: { "if-match": `W/${etag}` } });
  const any = await fetchFrom(bucket, "/data/v2/index.json", { method: "HEAD", headers: { "if-match": "*" } });
  const revalidation = await fetchFrom(bucket, "/data/v2/index.json", {
    method: "HEAD",
    headers: { "if-none-match": `W/${etag}` }
  });

  assert.deepEqual([strong.status, weak.status, any.status, revalidation.status], [200, 412, 200, 304]);
});

test("the Last-Modified this Worker sends is accepted back as not modified", async () => {
  // The object was uploaded at 20:00:00.789 and Last-Modified says 20:00:00.
  const bucket = bucketOf(PUBLISHED);
  const lastModified = (await fetchFrom(bucket, "/data/v2/index.json", { method: "HEAD" })).headers.get("last-modified");
  assert.equal(lastModified, "Mon, 05 Oct 2026 20:00:00 GMT");

  const since = await fetchFrom(bucket, "/data/v2/index.json", {
    method: "HEAD",
    headers: { "if-modified-since": lastModified }
  });
  const unmodified = await fetchFrom(bucket, "/data/v2/index.json", {
    method: "HEAD",
    headers: { "if-unmodified-since": lastModified }
  });

  assert.deepEqual([since.status, unmodified.status], [304, 200]);
});

test("a range is honoured only while the object is the version the client holds", async () => {
  const bucket = bucketOf(PUBLISHED);
  const whole = PUBLISHED["v2/index.json"];
  const etag = (await fetchFrom(bucket, "/data/v2/index.json", { method: "HEAD" })).headers.get("etag");

  const same = await fetchFrom(bucket, "/data/v2/index.json", {
    headers: { range: "bytes=2-5", "if-range": etag }
  });
  assert.equal(same.status, 206);
  assert.equal(same.headers.get("content-range"), `bytes 2-5/${whole.length}`);
  assert.equal(await same.text(), whole.slice(2, 6));

  // The index was republished since the client fetched its first part.
  const stale = await fetchFrom(bucket, "/data/v2/index.json", {
    headers: { range: "bytes=2-5", "if-range": '"the-version-before"' }
  });
  assert.equal(stale.status, 200);
  assert.equal(stale.headers.get("content-range"), null);
  assert.equal(await stale.text(), whole);

  const weak = await fetchFrom(bucket, "/data/v2/index.json", {
    headers: { range: "bytes=2-5", "if-range": `W/${etag}` }
  });
  assert.equal(weak.status, 200);

  const plain = await fetchFrom(bucket, "/data/v2/index.json", { headers: { range: "bytes=2-5" } });
  assert.equal(plain.status, 206);
});

// --- found in the second review ------------------------------------------------

test("If-Range is checked against the object the range was read from, not a look beforehand", async () => {
  // A publication lands between any earlier look at the index and the read:
  // `head` still describes version A, `get` returns version B.
  const versionB = new TextEncoder().encode('{"version":"B, the whole of it"}');
  const calls = [];
  const describe = (httpEtag) => ({
    size: versionB.byteLength,
    httpEtag,
    uploaded: new Date("2026-10-05T20:00:00Z"),
    writeHttpMetadata() {}
  });
  const bucket = {
    async head() {
      calls.push("head");
      return describe('"A"');
    },
    async get(_key, options) {
      const ranged = Boolean(options?.range);
      calls.push(ranged ? "get range" : "get whole");
      const bytes = ranged ? versionB.subarray(2, 6) : versionB;
      return {
        ...describe('"B"'),
        range: ranged ? { offset: 2, length: 4 } : { offset: 0, length: versionB.byteLength },
        body: new Blob([bytes]).stream()
      };
    }
  };

  const response = await fetchFrom(bucket, "/data/v2/index.json", {
    headers: { range: "bytes=2-5", "if-range": '"A"' }
  });

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("etag"), '"B"');
  assert.equal(response.headers.get("content-range"), null);
  assert.equal(await response.text(), '{"version":"B, the whole of it"}');
  assert.deepEqual(calls, ["get range", "get whole"]);
});

// --- found in review of the site and its Worker, 2026-10-17 -------------------

test("a range past the end is a 416 that gives the size, and is kept by no cache", async () => {
  const bucket = bucketOf(PUBLISHED);
  const size = PUBLISHED["v2/index.json"].length;

  // The deployed Worker answered this with 500, from R2's error.
  for (const range of ["bytes=99999999-", `bytes=${size}-`, `bytes=${size}-${size + 10}`, "bytes=-0"]) {
    const response = await fetchFrom(bucket, "/data/v2/index.json", { headers: { range } });
    assert.equal(response.status, 416, range);
    assert.equal(response.headers.get("content-range"), `bytes */${size}`, range);
    assert.equal(response.headers.get("cache-control"), "no-store", range);
    assert.equal(response.headers.get("access-control-allow-origin"), "*", range);
    assert.equal(await response.text(), "", range);
  }
});

test("a Range header that is not one range of bytes is ignored, and the whole object sent", async () => {
  const bucket = bucketOf(PUBLISHED);
  const whole = PUBLISHED["v2/index.json"];

  // The deployed Worker answered `bytes=abc` with a 206 of the whole object.
  for (const range of ["bytes=abc", "bytes=5-2", "bytes=-", "items=0-5", "bytes=0-1,4-5"]) {
    const response = await fetchFrom(bucket, "/data/v2/index.json", { headers: { range } });
    assert.equal(response.status, 200, range);
    assert.equal(response.headers.get("content-range"), null, range);
    assert.equal(response.headers.get("content-length"), String(whole.length), range);
    assert.equal(await response.text(), whole, range);
  }
});

test("a range from an offset, or of the last bytes, is a 206 of those bytes", async () => {
  const bucket = bucketOf(PUBLISHED);
  const whole = PUBLISHED["v2/index.json"];
  const size = whole.length;

  const tail = await fetchFrom(bucket, "/data/v2/index.json", { headers: { range: "bytes=-4" } });
  assert.equal(tail.status, 206);
  assert.equal(tail.headers.get("content-range"), `bytes ${size - 4}-${size - 1}/${size}`);
  assert.equal(tail.headers.get("content-length"), "4");
  assert.equal(await tail.text(), whole.slice(-4));

  const from = await fetchFrom(bucket, "/data/v2/index.json", { headers: { range: `bytes=${size - 3}-` } });
  assert.equal(from.status, 206);
  assert.equal(from.headers.get("content-range"), `bytes ${size - 3}-${size - 1}/${size}`);
  assert.equal(await from.text(), whole.slice(-3));

  // A range that runs past the end is cut there.
  const past = await fetchFrom(bucket, "/data/v2/index.json", { headers: { range: `bytes=${size - 2}-${size + 100}` } });
  assert.equal(past.status, 206);
  assert.equal(past.headers.get("content-range"), `bytes ${size - 2}-${size - 1}/${size}`);
});

test("past the end, a missing object is still a 404, a copy still current a 304, and a stale If-Range the whole object", async () => {
  const bucket = bucketOf(PUBLISHED);
  const whole = PUBLISHED["v2/index.json"];
  const etag = (await fetchFrom(bucket, "/data/v2/index.json", { method: "HEAD" })).headers.get("etag");

  const missing = await fetchFrom(bucket, "/data/v2/pointers/1.json", { headers: { range: "bytes=99999999-" } });
  assert.equal(missing.status, 404);

  // Preconditions are judged before a range.
  const current = await fetchFrom(bucket, "/data/v2/index.json", {
    headers: { range: "bytes=99999999-", "if-none-match": etag }
  });
  assert.equal(current.status, 304);

  const stale = await fetchFrom(bucket, "/data/v2/index.json", {
    headers: { range: "bytes=99999999-", "if-range": '"the-version-before"' }
  });
  assert.equal(stale.status, 200);
  assert.equal(await stale.text(), whole);
});

test("an error from R2 that is not about the range is still a fault", async () => {
  const bucket = bucketOf(PUBLISHED);
  bucket.get = async () => {
    throw new Error("R2 is down");
  };

  const response = await fetchFrom(bucket, "/data/v2/index.json", { headers: { range: "bytes=0-3" } });

  assert.equal(response.status, 500);
  assert.equal((await response.json()).code, "worker_error");
});

test("a page on another origin may send the headers of a range or a conditional request", async () => {
  const bucket = bucketOf(PUBLISHED);

  const preflight = await fetchFrom(bucket, "/data/v2/index.json", {
    method: "OPTIONS",
    headers: {
      origin: "https://formula1data.pages.dev",
      "access-control-request-method": "GET",
      "access-control-request-headers": "range, if-none-match"
    }
  });

  assert.equal(preflight.status, 204);
  const allowed = preflight.headers.get("access-control-allow-headers").split(/,\s*/);
  for (const name of ["range", "if-match", "if-none-match", "if-modified-since", "if-unmodified-since", "if-range"]) {
    assert.ok(allowed.includes(name), name);
  }
  assert.deepEqual(bucket.calls, []);
});
