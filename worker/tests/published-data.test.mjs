import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/index.mjs";
import {
  getPublishedData,
  isPublishedDataKey,
  publishedDataCacheControl
} from "../src/published-data.mjs";
import { serveR2Object } from "../src/r2-response.mjs";

const context = { waitUntil() {} };

const IMMUTABLE = "public, max-age=31536000, immutable";
const MUTABLE = "public, max-age=30, stale-while-revalidate=120";

const SESSION_KEY = "9939";
const GENERATION_A = "a1".repeat(32);
const GENERATION_B = "b2".repeat(32);

function generationKey(generationId, file, version = "v1") {
  return `${version}/generations/${SESSION_KEY}/${generationId}/${file}`;
}

// An in-memory stand-in for the R2 binding. It behaves like R2 in the three
// places the Worker depends on: `head` returns metadata only, a `get` whose
// `onlyIf` fails returns metadata without a body, and a ranged `get` reports
// the range it returned. Every call is recorded, so a test can show which keys
// the Worker asked for and that it asked for nothing else.
function fakeBucket() {
  const objects = new Map();
  const calls = [];
  let writes = 0;

  function metadata(stored) {
    return {
      size: stored.bytes.byteLength,
      httpEtag: stored.httpEtag,
      uploaded: stored.uploaded,
      writeHttpMetadata(headers) {
        if (stored.contentType) {
          headers.set("content-type", stored.contentType);
        }
      }
    };
  }

  return {
    calls,
    put(key, text, { contentType = null, uploaded = new Date("2026-10-04T15:00:00Z") } = {}) {
      writes += 1;
      objects.set(key, {
        bytes: new TextEncoder().encode(text),
        httpEtag: `"etag-${writes}"`,
        uploaded,
        contentType
      });
    },
    async head(key) {
      calls.push(`head ${key}`);
      const stored = objects.get(key);
      return stored ? metadata(stored) : null;
    },
    async get(key, options) {
      calls.push(`get ${key}`);
      const stored = objects.get(key);
      if (!stored) {
        return null;
      }
      if (options?.onlyIf && !preconditionsHold(stored, options.onlyIf)) {
        return metadata(stored);
      }
      const range = requestedRange(options?.range, stored.bytes.byteLength);
      const bytes = range ? stored.bytes.subarray(range.offset, range.offset + range.length) : stored.bytes;
      return {
        ...metadata(stored),
        ...(range ? { range } : {}),
        body: new Blob([bytes]).stream()
      };
    }
  };
}

function preconditionsHold(stored, headers) {
  const ifMatch = headers.get("if-match");
  if (ifMatch && ifMatch !== stored.httpEtag) {
    return false;
  }
  const ifNoneMatch = headers.get("if-none-match");
  if (ifNoneMatch) {
    return ifNoneMatch.replace(/^W\//, "") !== stored.httpEtag;
  }
  const ifModifiedSince = Date.parse(headers.get("if-modified-since") || "");
  return !(Number.isFinite(ifModifiedSince) && stored.uploaded.getTime() <= ifModifiedSince);
}

function requestedRange(headers, size) {
  const match = /^bytes=(\d+)-(\d*)$/.exec(headers?.get("range") || "");
  if (!match) {
    return null;
  }
  const offset = Number(match[1]);
  const end = match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  return { offset, length: end - offset + 1 };
}

function fetchData(env, path, init) {
  return worker.fetch(new Request(`https://worker.example${path}`, init), env, context);
}

// Stands in for the static site behind STATIC_DATA_BASE_URL, and has an answer
// for every path. A request that reached the fallback would therefore come back
// as a 200, not as the 404 these tests expect, as well as showing up in `urls`.
async function withStaticSite(run) {
  const previousFetch = globalThis.fetch;
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    return new Response('{"from":"static"}', {
      status: 200,
      headers: { "content-type": "application/json", "content-length": "17" }
    });
  };
  try {
    return await run(urls);
  } finally {
    globalThis.fetch = previousFetch;
  }
}

function envWithStaticSite(bucket) {
  return {
    ARTIFACTS_BUCKET: bucket,
    STATIC_DATA_BASE_URL: "https://formula1data.pages.dev/data",
    LOCAL_STATIC_DATA_BASE_URL: "http://localhost:3000/data"
  };
}

test("a generation key is served as given and may be cached for good", async () => {
  const bucket = fakeBucket();
  const files = {
    "manifest.json": '{"schema_version":1}',
    "summary.json": '{"winner":"VER"}',
    "laps.json": '{"laps":[]}',
    "analysis/race-pace.json": '{"pace":[]}',
    "telemetry/ver.json": '{"speed":[]}'
  };
  for (const [file, body] of Object.entries(files)) {
    bucket.put(generationKey(GENERATION_A, file), body);
  }

  for (const [file, body] of Object.entries(files)) {
    const key = generationKey(GENERATION_A, file);
    bucket.calls.length = 0;
    const response = await fetchData({ ARTIFACTS_BUCKET: bucket }, `/data/${key}`);

    assert.equal(response.status, 200, key);
    assert.equal(await response.text(), body);
    assert.equal(response.headers.get("content-type"), "application/json; charset=utf-8");
    assert.equal(response.headers.get("cache-control"), IMMUTABLE);
    assert.equal(response.headers.get("content-length"), String(body.length));
    assert.match(response.headers.get("etag"), /^"etag-\d+"$/);
    assert.equal(response.headers.get("last-modified"), "Sun, 04 Oct 2026 15:00:00 GMT");
    assert.equal(response.headers.get("accept-ranges"), "bytes");
    // One read, of the key in the URL: nothing was resolved on the way.
    assert.deepEqual(bucket.calls, [`get ${key}`]);
  }
});

test("the index, a pointer and the standings are served as given with a short cache life", async () => {
  const bucket = fakeBucket();
  const objects = {
    "v1/index.json": '{"sessions":[]}',
    [`v1/pointers/${SESSION_KEY}.json`]: `{"generation_id":"${GENERATION_A}"}`,
    "v1/standings/2026.json": '{"drivers":[]}'
  };
  for (const [key, body] of Object.entries(objects)) {
    bucket.put(key, body);
  }

  for (const [key, body] of Object.entries(objects)) {
    bucket.calls.length = 0;
    const response = await fetchData({ ARTIFACTS_BUCKET: bucket }, `/data/${key}`);

    assert.equal(response.status, 200, key);
    assert.equal(await response.text(), body);
    assert.equal(response.headers.get("content-type"), "application/json; charset=utf-8");
    assert.equal(response.headers.get("cache-control"), MUTABLE);
    assert.deepEqual(bucket.calls, [`get ${key}`]);
  }
});

test("a content type stored with the object is kept, and the key decides only when there is none", async () => {
  const bucket = fakeBucket();
  const stored = generationKey(GENERATION_A, "summary.json");
  const derived = generationKey(GENERATION_A, "telemetry/ver.bin");
  bucket.put(stored, "{}", { contentType: "application/json" });
  bucket.put(derived, "0123");

  const withMetadata = await fetchData({ ARTIFACTS_BUCKET: bucket }, `/data/${stored}`);
  const withoutMetadata = await fetchData({ ARTIFACTS_BUCKET: bucket }, `/data/${derived}`);

  assert.equal(withMetadata.headers.get("content-type"), "application/json");
  assert.equal(withoutMetadata.headers.get("content-type"), "application/octet-stream");
});

test("a later format version is served without a code change", async () => {
  const bucket = fakeBucket();
  const expected = {
    "v2/index.json": MUTABLE,
    "v2/pointers/9939.json": MUTABLE,
    [generationKey(GENERATION_A, "laps.json", "v2")]: IMMUTABLE,
    "v10/standings/2027.json": MUTABLE,
    [generationKey(GENERATION_B, "telemetry/ver.json", "v123")]: IMMUTABLE
  };
  for (const key of Object.keys(expected)) {
    bucket.put(key, `{"key":"${key}"}`);
  }

  for (const [key, cacheControl] of Object.entries(expected)) {
    const response = await fetchData({ ARTIFACTS_BUCKET: bucket }, `/data/${key}`);

    assert.equal(response.status, 200, key);
    assert.deepEqual(await response.json(), { key });
    assert.equal(response.headers.get("cache-control"), cacheControl, key);
  }
});

test("an absent published key is a 404 and the static site is never asked", async () => {
  const absent = [
    "v1/index.json",
    `v1/pointers/${SESSION_KEY}.json`,
    "v1/standings/2026.json",
    generationKey(GENERATION_A, "laps.json"),
    "v2/index.json"
  ];

  await withStaticSite(async (staticRequests) => {
    for (const key of absent) {
      for (const method of ["GET", "HEAD"]) {
        const bucket = fakeBucket();
        const response = await fetchData(envWithStaticSite(bucket), `/data/${key}`, { method });

        assert.equal(response.status, 404, `${method} ${key}`);
        assert.deepEqual(await response.json(), {
          code: "artifact_not_found",
          message: "Artifact was not found",
          details: { path: key }
        });
        // R2 was asked once, by the method that suits the request, and that
        // answer was final.
        assert.deepEqual(bucket.calls, [`${method.toLowerCase()} ${key}`]);
      }
    }
    assert.deepEqual(staticRequests, []);
  });
});

test("the legacy layout keeps its static fallback and its own cache policy beside the new one", async () => {
  const bucket = fakeBucket();
  bucket.put("sessions/2026-01-r/summary.json", '{"from":"r2"}');
  const env = envWithStaticSite(bucket);

  await withStaticSite(async (staticRequests) => {
    const fromR2 = await fetchData(env, "/data/sessions/2026-01-r/summary.json");
    assert.equal(fromR2.status, 200);
    assert.deepEqual(await fromR2.json(), { from: "r2" });
    assert.equal(fromR2.headers.get("cache-control"), "public, max-age=30, stale-while-revalidate=300");
    assert.deepEqual(staticRequests, []);

    const catalog = await fetchData(env, "/data/catalog.json");
    assert.equal(catalog.status, 200);
    assert.deepEqual(await catalog.json(), { from: "static" });
    assert.equal(catalog.headers.get("cache-control"), "public, max-age=120, stale-while-revalidate=600");

    const season = await fetchData(env, "/data/seasons/2026.json");
    assert.deepEqual(await season.json(), { from: "static" });

    const session = await fetchData(env, "/data/sessions/2026-02-r/summary.json");
    assert.deepEqual(await session.json(), { from: "static" });
    assert.equal(session.headers.get("cache-control"), "public, max-age=30, stale-while-revalidate=300");

    assert.deepEqual(staticRequests, [
      "https://formula1data.pages.dev/data/catalog.json",
      "https://formula1data.pages.dev/data/seasons/2026.json",
      "https://formula1data.pages.dev/data/sessions/2026-02-r/summary.json"
    ]);
  });
});

test("the source archive is a 404 even when the object exists", async () => {
  const bucket = fakeBucket();
  const archived = [
    "archive/9939/2026-10-04T15-00-00Z/cache.tar.zst",
    "archive/9939/snapshot.json",
    // An archive key that happens to contain a version segment is still archive.
    "archive/v1/index.json"
  ];
  for (const key of archived) {
    bucket.put(key, '{"private":true}');
  }

  await withStaticSite(async (staticRequests) => {
    for (const key of archived) {
      for (const method of ["GET", "HEAD"]) {
        const response = await fetchData(envWithStaticSite(bucket), `/data/${key}`, { method });

        assert.equal(response.status, 404, `${method} ${key}`);
        assert.equal((await response.json()).code, "artifact_not_found");
      }
    }
    // Not served, and not even looked up: neither store saw the key.
    assert.deepEqual(bucket.calls, []);
    assert.deepEqual(staticRequests, []);
  });
});

test("only a v<N>/ prefix with something after it is a published key", async () => {
  const bucket = fakeBucket();
  const notPublished = [
    "v0/index.json",
    "v/index.json",
    "vx/index.json",
    "v01/index.json",
    "v1x/index.json",
    "v-1/index.json",
    "V1/index.json",
    "1/index.json",
    "xv1/index.json",
    "pointers/9939.json",
    "generations/9939/laps.json",
    "v1",
    "v2",
    "v1.json"
  ];
  for (const key of notPublished) {
    bucket.put(key, '{"served":"wrongly"}');
  }

  await withStaticSite(async (staticRequests) => {
    for (const key of notPublished) {
      const response = await fetchData(envWithStaticSite(bucket), `/data/${key}`);

      assert.equal(response.status, 404, key);
      assert.equal((await response.json()).code, "artifact_not_found");
    }
    assert.deepEqual(bucket.calls, []);
    assert.deepEqual(staticRequests, []);
  });
});

test("a matching If-None-Match is answered with 304 and no body", async () => {
  const bucket = fakeBucket();
  const key = generationKey(GENERATION_A, "laps.json");
  bucket.put(key, '{"laps":[]}');
  const env = { ARTIFACTS_BUCKET: bucket };
  const etag = (await fetchData(env, `/data/${key}`)).headers.get("etag");

  // A cache in between may have weakened the validator; both forms name the
  // same stored object.
  for (const validator of [etag, `W/${etag}`]) {
    for (const method of ["GET", "HEAD"]) {
      const response = await fetchData(env, `/data/${key}`, {
        method,
        headers: { "if-none-match": validator }
      });

      assert.equal(response.status, 304, `${method} ${validator}`);
      assert.equal(response.body, null);
      assert.equal(response.headers.get("etag"), etag);
      assert.equal(response.headers.get("cache-control"), IMMUTABLE);
      assert.equal(response.headers.get("content-length"), null);
    }
  }
});

test("the other preconditions behave as they do on the legacy R2 path", async () => {
  const bucket = fakeBucket();
  const key = `v1/pointers/${SESSION_KEY}.json`;
  bucket.put(key, '{"generation_id":"a"}');
  const env = { ARTIFACTS_BUCKET: bucket };
  const first = await fetchData(env, `/data/${key}`);
  const etag = first.headers.get("etag");
  const lastModified = first.headers.get("last-modified");

  const stale = await fetchData(env, `/data/${key}`, { headers: { "if-none-match": '"some-other-etag"' } });
  assert.equal(stale.status, 200);
  assert.equal(await stale.text(), '{"generation_id":"a"}');

  const unmodified = await fetchData(env, `/data/${key}`, { headers: { "if-modified-since": lastModified } });
  assert.equal(unmodified.status, 304);
  assert.equal(unmodified.body, null);
  assert.equal(unmodified.headers.get("cache-control"), MUTABLE);

  const matched = await fetchData(env, `/data/${key}`, { headers: { "if-match": etag } });
  assert.equal(matched.status, 200);

  const mismatched = await fetchData(env, `/data/${key}`, { headers: { "if-match": '"some-other-etag"' } });
  assert.equal(mismatched.status, 412);
  assert.equal(mismatched.body, null);

  const changedSince = await fetchData(env, `/data/${key}`, {
    headers: { "if-unmodified-since": "Sat, 03 Oct 2026 15:00:00 GMT" }
  });
  assert.equal(changedSince.status, 412);
});

test("a Range request is answered with 206 and the bytes asked for", async () => {
  const bucket = fakeBucket();
  const key = generationKey(GENERATION_A, "telemetry/ver.json");
  bucket.put(key, "0123456789");
  const env = { ARTIFACTS_BUCKET: bucket };

  const middle = await fetchData(env, `/data/${key}`, { headers: { range: "bytes=2-5" } });
  assert.equal(middle.status, 206);
  assert.equal(middle.headers.get("content-range"), "bytes 2-5/10");
  assert.equal(middle.headers.get("content-length"), "4");
  assert.equal(middle.headers.get("cache-control"), IMMUTABLE);
  assert.equal(await middle.text(), "2345");

  const tail = await fetchData(env, `/data/${key}`, { headers: { range: "bytes=7-" } });
  assert.equal(tail.status, 206);
  assert.equal(tail.headers.get("content-range"), "bytes 7-9/10");
  assert.equal(await tail.text(), "789");

  const whole = await fetchData(env, `/data/${key}`);
  assert.equal(whole.status, 200);
  assert.equal(whole.headers.get("content-range"), null);
  assert.equal(whole.headers.get("content-length"), "10");
});

test("HEAD returns the headers of a GET and no body, without reading the object", async () => {
  const bucket = fakeBucket();
  const generation = generationKey(GENERATION_A, "laps.json");
  const pointer = `v1/pointers/${SESSION_KEY}.json`;
  bucket.put(generation, '{"laps":[]}');
  bucket.put(pointer, '{"generation_id":"a"}');
  const env = { ARTIFACTS_BUCKET: bucket };

  for (const [key, cacheControl] of [[generation, IMMUTABLE], [pointer, MUTABLE]]) {
    const viaGet = await fetchData(env, `/data/${key}`);
    await viaGet.body?.cancel();
    bucket.calls.length = 0;
    const response = await fetchData(env, `/data/${key}`, { method: "HEAD" });

    assert.equal(response.status, 200, key);
    assert.equal(response.body, null);
    assert.equal(await response.text(), "");
    assert.equal(response.headers.get("cache-control"), cacheControl);
    for (const name of ["content-type", "content-length", "etag", "last-modified", "accept-ranges"]) {
      assert.equal(response.headers.get(name), viaGet.headers.get(name), `${key} ${name}`);
    }
    assert.deepEqual(bucket.calls, [`head ${key}`]);
  }
});

test("a traversal out of the version prefix is rejected with a 400", async () => {
  const bucket = fakeBucket();
  bucket.put("archive/secret.json", '{"private":true}');
  bucket.put("v1/index.json", "{}");
  const rejected = [
    // An encoded slash keeps `..` out of sight of the URL parser, which would
    // otherwise collapse it before the Worker saw the path.
    "/data/v1/..%2Farchive/secret.json",
    "/data/v1/generations/..%2F..%2F..%2Farchive/secret.json",
    "/data/v1/%2E%2E%2Farchive/secret.json",
    "/data/v1/..%5Carchive%5Csecret.json",
    "/data/v1/pointers%2F..%2F..%2Farchive%2Fsecret.json",
    // Other shapes the shared validator refuses under the new prefix too.
    "/data/v1/",
    "/data/v1//index.json",
    "/data/v1/.%2Findex.json",
    "/data/v1/%E0%A4%A"
  ];

  await withStaticSite(async (staticRequests) => {
    for (const path of rejected) {
      for (const method of ["GET", "HEAD"]) {
        const response = await fetchData(envWithStaticSite(bucket), path, { method });

        assert.equal(response.status, 400, `${method} ${path}`);
        assert.equal((await response.json()).code, "invalid_artifact_path");
      }
    }
    assert.deepEqual(bucket.calls, []);
    assert.deepEqual(staticRequests, []);
  });
});

test("a literal .. is collapsed by the URL parser and the path it leaves is judged on its own", async () => {
  const bucket = fakeBucket();
  bucket.put("archive/secret.json", '{"private":true}');
  bucket.put("v1/index.json", '{"sessions":[]}');
  const env = { ARTIFACTS_BUCKET: bucket };

  // `/data/v1/../archive/secret.json` reaches the Worker as `/data/archive/secret.json`.
  for (const path of ["/data/v1/../archive/secret.json", "/data/v1/%2e%2e/archive/secret.json"]) {
    const escaped = await fetchData(env, path);
    assert.equal(escaped.status, 404, path);
  }
  assert.deepEqual(bucket.calls, []);

  // The same collapsing inside the prefix lands on an ordinary published key.
  const inside = await fetchData(env, "/data/v1/pointers/../index.json");
  assert.equal(inside.status, 200);
  assert.deepEqual(bucket.calls, ["get v1/index.json"]);

  // A doubly encoded traversal decodes once, to a key with a literal `%` in it.
  // That is a strange key, not a traversal, and it is looked up as given.
  bucket.calls.length = 0;
  const doubled = await fetchData(env, "/data/v1/%252e%252e%252farchive/secret.json");
  assert.equal(doubled.status, 404);
  assert.deepEqual(bucket.calls, ["get v1/%2e%2e%2farchive/secret.json"]);
});

test("a superseded generation still serves its own bytes after the pointer names the next one", async () => {
  const bucket = fakeBucket();
  const env = { ARTIFACTS_BUCKET: bucket };
  const pointerKey = `v1/pointers/${SESSION_KEY}.json`;
  const files = ["summary.json", "laps.json", "analysis/race-pace.json"];

  for (const file of files) {
    bucket.put(generationKey(GENERATION_A, file), JSON.stringify({ generation: "A", file }));
  }
  bucket.put(pointerKey, JSON.stringify({ session_key: SESSION_KEY, generation_id: GENERATION_A }));

  // A page opens: it reads the pointer once and pins what it names.
  const firstPointer = await fetchData(env, `/data/${pointerKey}`);
  const pointerEtag = firstPointer.headers.get("etag");
  const pinned = (await firstPointer.json()).generation_id;
  assert.equal(pinned, GENERATION_A);
  const summary = await fetchData(env, `/data/${generationKey(pinned, "summary.json")}`);
  assert.deepEqual(await summary.json(), { generation: "A", file: "summary.json" });

  // A second publication lands while that page is still open: the new
  // generation first, the pointer last.
  for (const file of files) {
    bucket.put(generationKey(GENERATION_B, file), JSON.stringify({ generation: "B", file }));
  }
  bucket.put(pointerKey, JSON.stringify({ session_key: SESSION_KEY, generation_id: GENERATION_B }));

  // The open page loads its remaining tabs from the generation it pinned. Each
  // one is a single read of the key in the URL: the pointer is not consulted,
  // so the view cannot end up with one file from each generation.
  for (const file of ["laps.json", "analysis/race-pace.json"]) {
    const key = generationKey(pinned, file);
    bucket.calls.length = 0;
    const response = await fetchData(env, `/data/${key}`);

    assert.equal(response.status, 200, file);
    assert.deepEqual(await response.json(), { generation: "A", file });
    assert.equal(response.headers.get("cache-control"), IMMUTABLE);
    assert.deepEqual(bucket.calls, [`get ${key}`]);
  }

  // A page that opens now, or one that revalidates the pointer it holds, sees
  // the new generation and reads that one whole.
  const revalidated = await fetchData(env, `/data/${pointerKey}`, { headers: { "if-none-match": pointerEtag } });
  assert.equal(revalidated.status, 200);
  assert.equal(revalidated.headers.get("cache-control"), MUTABLE);
  const current = (await revalidated.json()).generation_id;
  assert.equal(current, GENERATION_B);
  for (const file of files) {
    const response = await fetchData(env, `/data/${generationKey(current, file)}`);
    assert.deepEqual(await response.json(), { generation: "B", file });
  }
});

test("a missing bucket binding is a fault for published keys, not a 404", async () => {
  await withStaticSite(async (staticRequests) => {
    const response = await fetchData(
      { STATIC_DATA_BASE_URL: "https://formula1data.pages.dev/data" },
      "/data/v1/index.json"
    );

    assert.equal(response.status, 500);
    assert.equal((await response.json()).code, "worker_error");
    assert.deepEqual(staticRequests, []);
  });
});

test("only GET and HEAD reach published data", async () => {
  const bucket = fakeBucket();
  bucket.put("v1/index.json", "{}");

  for (const method of ["POST", "PUT", "DELETE"]) {
    const response = await fetchData({ ARTIFACTS_BUCKET: bucket }, "/data/v1/index.json", { method });

    assert.equal(response.status, 404, method);
    assert.equal((await response.json()).code, "not_found");
  }
  assert.deepEqual(bucket.calls, []);
});

test("isPublishedDataKey and publishedDataCacheControl classify keys by prefix alone", () => {
  const published = ["v1/index.json", "v1/pointers/9939.json", "v2/x", "v10/standings/2026.json", "v1/archive/x.json"];
  const notPublished = [
    "archive/x.json",
    "v0/x",
    "v/x",
    "vx/x",
    "v01/x",
    "v1",
    "v1/",
    "catalog.json",
    "sessions/v1/x",
    "",
    null,
    undefined
  ];
  for (const key of published) {
    assert.equal(isPublishedDataKey(key), true, key);
  }
  for (const key of notPublished) {
    assert.equal(isPublishedDataKey(key), false, String(key));
  }

  assert.equal(publishedDataCacheControl(generationKey(GENERATION_A, "manifest.json")), IMMUTABLE);
  assert.equal(publishedDataCacheControl(generationKey(GENERATION_A, "laps.json", "v7")), IMMUTABLE);
  assert.equal(publishedDataCacheControl("v1/index.json"), MUTABLE);
  assert.equal(publishedDataCacheControl(`v1/pointers/${SESSION_KEY}.json`), MUTABLE);
  assert.equal(publishedDataCacheControl("v1/standings/2026.json"), MUTABLE);
  // Only the segment directly under the version marks a generation.
  assert.equal(publishedDataCacheControl("v1/pointers/generations/x.json"), MUTABLE);
  assert.equal(publishedDataCacheControl("v1/generations.json"), MUTABLE);
});

test("getPublishedData does not read a key outside the published layout when called directly", async () => {
  const bucket = fakeBucket();
  bucket.put("archive/secret.json", '{"private":true}');
  bucket.put("catalog.json", "{}");
  const env = { ARTIFACTS_BUCKET: bucket };

  assert.equal(await getPublishedData(env, "archive/secret.json"), null);
  assert.equal(await getPublishedData(env, "catalog.json"), null);
  assert.deepEqual(bucket.calls, []);
});

test("the shared R2 response takes its cache policy from the caller and refuses to go without one", async () => {
  const bucket = fakeBucket();
  bucket.put("any/key.json", "{}");

  const response = await serveR2Object(bucket, "any/key.json", null, "private, max-age=5");
  assert.equal(response.headers.get("cache-control"), "private, max-age=5");
  await response.body?.cancel();

  await assert.rejects(() => serveR2Object(bucket, "any/key.json", null, undefined), /cache-control/);
  assert.equal(await serveR2Object(bucket, "missing.json", null, "private, max-age=5"), null);
});
