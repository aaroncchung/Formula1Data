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
    async get(_key, options) {
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
