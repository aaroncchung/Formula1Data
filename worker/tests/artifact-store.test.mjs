import assert from "node:assert/strict";
import test from "node:test";

import { createArtifactStore } from "../src/artifact-store.mjs";

function r2Object(body, overrides = {}) {
  return {
    body,
    size: 10,
    httpEtag: '"artifact-etag"',
    uploaded: new Date("2026-07-12T12:00:00Z"),
    writeHttpMetadata(headers) {
      headers.set("content-type", "application/json");
    },
    ...overrides
  };
}

test("R2 artifacts are streamed with range and cache metadata", async () => {
  let receivedOptions;
  const bucket = {
    async get(key, options) {
      // A session with no generation pointer -- the legacy layout. Answering
      // this key with a body would claim the session is generation-published
      // and then fail to parse as a pointer, which is a different test.
      if (key.endsWith("active.json")) {
        return null;
      }
      receivedOptions = options;
      return r2Object(new Blob(["0123"]).stream(), {
        range: { offset: 2, length: 4 }
      });
    }
  };
  const request = new Request("https://worker.example/data/sessions/2026-01-r/summary.json", {
    headers: { range: "bytes=2-5" }
  });
  const response = await createArtifactStore({ ARTIFACTS_BUCKET: bucket }).get(
    "/data/sessions/2026-01-r/summary.json",
    request
  );

  assert.equal(response.status, 206);
  assert.equal(response.headers.get("content-range"), "bytes 2-5/10");
  assert.equal(response.headers.get("content-length"), "4");
  assert.equal(response.headers.get("etag"), '"artifact-etag"');
  assert.equal(response.headers.get("accept-ranges"), "bytes");
  assert.equal(receivedOptions.range.get("range"), "bytes=2-5");
  assert.equal(await response.text(), "0123");
});

test("conditional R2 responses return 304 without buffering an object body", async () => {
  const bucket = {
    async get(_key, options) {
      assert.equal(options.onlyIf.get("if-none-match"), '"artifact-etag"');
      return r2Object(undefined);
    }
  };
  const request = new Request("https://worker.example/data/catalog.json", {
    headers: { "if-none-match": '"artifact-etag"' }
  });
  const response = await createArtifactStore({ ARTIFACTS_BUCKET: bucket }).get("catalog.json", request);

  assert.equal(response.status, 304);
  assert.equal(response.body, null);
  assert.equal(response.headers.get("etag"), '"artifact-etag"');
});

test("HEAD artifact requests use R2 metadata without reading the object", async () => {
  let getCalls = 0;
  const bucket = {
    async head() {
      return r2Object(undefined, { size: 42 });
    },
    async get() {
      getCalls += 1;
      return null;
    }
  };
  const response = await createArtifactStore({ ARTIFACTS_BUCKET: bucket }).get(
    "catalog.json",
    new Request("https://worker.example/data/catalog.json", { method: "HEAD" })
  );

  assert.equal(response.status, 200);
  assert.equal(response.body, null);
  assert.equal(response.headers.get("content-length"), "42");
  assert.equal(getCalls, 0);
});

async function withStubbedFallback(status, run) {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    const headers = {
      etag: '"fallback-etag"',
      "last-modified": "Sun, 12 Jul 2026 12:00:00 GMT"
    };
    if (status === 416) {
      headers["content-range"] = "bytes */10";
    }
    const hasBody = status !== 304;
    if (hasBody) {
      headers["content-length"] = "2";
    }
    return new Response(hasBody ? "{}" : null, { status, headers });
  };
  try {
    return await run(createArtifactStore({ STATIC_DATA_BASE_URL: "https://formula1data.pages.dev/data" }));
  } finally {
    globalThis.fetch = previousFetch;
  }
}

// Probe table from finding F-07: `get()` must accept the same fallback statuses
// as `head()`, otherwise a conditional 304 or a 416 is reported as a 404.
const FALLBACK_PROBES = [
  { status: 200, passesThrough: true },
  { status: 206, passesThrough: true },
  { status: 304, passesThrough: true },
  { status: 416, passesThrough: true },
  { status: 404, passesThrough: false },
  { status: 500, passesThrough: false }
];

for (const { status, passesThrough } of FALLBACK_PROBES) {
  test(`fallback ${status} ${passesThrough ? "passes through" : "is treated as a miss"} in get()`, async () => {
    const response = await withStubbedFallback(status, (store) => store.get("catalog.json"));

    if (!passesThrough) {
      assert.equal(response, null);
      return;
    }

    assert.ok(response instanceof Response);
    assert.equal(response.status, status);
    assert.equal(response.headers.get("etag"), '"fallback-etag"');
    assert.equal(response.headers.get("cache-control"), "public, max-age=120, stale-while-revalidate=600");
    assert.equal(response.headers.get("accept-ranges"), "bytes");
    if (status === 304) {
      assert.equal(response.body, null);
    }
    if (status === 416) {
      assert.equal(response.headers.get("content-range"), "bytes */10");
    }
    await response.body?.cancel();
  });

  test(`fallback ${status} ${passesThrough ? "resolves" : "is treated as a miss"} in head()`, async () => {
    const metadata = await withStubbedFallback(status, (store) => store.head("catalog.json"));

    if (!passesThrough) {
      assert.equal(metadata, null);
      return;
    }
    assert.equal(metadata.key, "catalog.json");
    assert.equal(metadata.etag, '"fallback-etag"');
  });
}

test("a conditional fallback 304 is forwarded rather than reported as artifact_not_found", async () => {
  const previousFetch = globalThis.fetch;
  let forwardedIfNoneMatch = null;
  globalThis.fetch = async (_url, init) => {
    forwardedIfNoneMatch = new Headers(init?.headers).get("if-none-match");
    return new Response(null, { status: 304, headers: { etag: '"fallback-etag"' } });
  };
  try {
    const store = createArtifactStore({ STATIC_DATA_BASE_URL: "https://formula1data.pages.dev/data" });
    const response = await store.get(
      "sessions/2026-09-r/summary.json",
      new Request("https://worker.example/data/sessions/2026-09-r/summary.json", {
        headers: { "if-none-match": '"fallback-etag"' }
      })
    );

    assert.equal(forwardedIfNoneMatch, '"fallback-etag"');
    assert.equal(response.status, 304);
    assert.equal(response.headers.get("cache-control"), "public, max-age=30, stale-while-revalidate=300");
  } finally {
    globalThis.fetch = previousFetch;
  }
});

for (const baseUrl of ["https://formula1data.pages.dev/data", "https://formula1data.pages.dev/data/"]) {
  test(`fallback joins the exact Pages data URL from ${baseUrl}`, async () => {
    const previousFetch = globalThis.fetch;
    const urls = [];
    globalThis.fetch = async (url) => {
      urls.push(String(url));
      return new Response("{}", {
        status: 200,
        headers: { "content-type": "application/json", "content-length": "2" }
      });
    };
    try {
      const store = createArtifactStore({ STATIC_DATA_BASE_URL: baseUrl });
      await store.get("catalog.json");
      await store.get("sessions/2026-09-r/summary.json");
      assert.deepEqual(urls, [
        "https://formula1data.pages.dev/data/catalog.json",
        "https://formula1data.pages.dev/data/sessions/2026-09-r/summary.json"
      ]);
    } finally {
      globalThis.fetch = previousFetch;
    }
  });
}
