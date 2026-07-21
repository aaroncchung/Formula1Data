import assert from "node:assert/strict";
import test from "node:test";

import { createArtifactStore } from "../src/artifact-store.mjs";

async function record(path, kind, value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const checksum = `sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
  return { path, kind, size_bytes: bytes.byteLength, checksum, bytes };
}

function bucketFor(records) {
  const objects = new Map(records.map((item) => [item.path, item]));
  const requests = [];
  return {
    requests,
    async get(key) {
      requests.push(key);
      const item = objects.get(key);
      return item ? r2Object(new Blob([item.bytes]).stream(), { size: item.bytes.byteLength }) : null;
    }
  };
}

function artifactRecord(path, kind) {
  return { path, kind, size_bytes: 2, checksum: `sha256:${"0".repeat(64)}` };
}

async function publicationFor(sessionId, sections, manifestSessionId = sessionId) {
  const manifest = await record(`sessions/${sessionId}/manifest.json`, "manifest", {
    schema_version: 1,
    session_id: manifestSessionId,
    sections
  });
  const generationId = manifest.checksum.slice("sha256:".length);
  const base = `sessions/${sessionId}/generations/${generationId}`;
  const generationManifest = { ...manifest, path: `${base}/manifest.json` };
  const pointer = await record(`sessions/${sessionId}/active.json`, "active", {
    schema_version: 1,
    session_id: sessionId,
    artifact_base_path: base,
    manifest: { size_bytes: manifest.size_bytes, checksum: manifest.checksum }
  });
  return { manifest, generationManifest, pointer, base };
}

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
      if (key.endsWith("/active.json")) return null;
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

test("artifact metadata identifies canonical and generation-backed R2 keys", async () => {
  const sessionId = "2026-01-r";
  const canonicalKey = `sessions/${sessionId}/manifest.json`;
  const generationId = "a".repeat(64);
  const generationKey = `sessions/${sessionId}/generations/${generationId}/manifest.json`;
  const pointer = JSON.stringify({
    schema_version: 1,
    session_id: sessionId,
    artifact_base_path: `sessions/${sessionId}/generations/${generationId}`,
    manifest: { size_bytes: 42, checksum: `sha256:${generationId}` }
  });
  const bucket = {
    active: false,
    async get(key) {
      return this.active && key.endsWith("/active.json")
        ? r2Object(new Blob([pointer]).stream(), { size: pointer.length })
        : null;
    },
    async head(key) {
      return [canonicalKey, generationKey].includes(key)
        ? r2Object(undefined, { size: 42 })
        : null;
    }
  };

  const canonical = await createArtifactStore({ ARTIFACTS_BUCKET: bucket }).head(canonicalKey);
  bucket.active = true;
  const generated = await createArtifactStore({ ARTIFACTS_BUCKET: bucket }).head(canonicalKey);

  assert.equal(canonical.source, "r2");
  assert.equal(canonical.storage_key, canonicalKey);
  assert.equal(generated.source, "r2");
  assert.equal(generated.storage_key, generationKey);
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

test("active manifest verification stays bounded for large publications", async () => {
  const sessionId = "2026-09-r";
  const sections = [artifactRecord(`sessions/${sessionId}/summary.json`, "summary")];
  for (let lap = 1; lap < 1_500; lap += 1) {
    sections.push(artifactRecord(`sessions/${sessionId}/telemetry/driver-lap-${lap}.json`, "telemetry-lap"));
  }
  const publication = await publicationFor(sessionId, sections);
  const bucket = bucketFor([publication.pointer, publication.generationManifest]);

  const result = await createArtifactStore({ ARTIFACTS_BUCKET: bucket })
    .verifyManifest(publication.manifest, { r2Only: true });

  assert.equal(result.verified, true);
  assert.equal(result.artifact_count, 1_500);
  assert.deepEqual(bucket.requests, [publication.pointer.path, publication.generationManifest.path]);
});

test("manifest verification requires a valid active pointer matching the callback", async () => {
  const sessionId = "2026-09-r";
  const publication = await publicationFor(sessionId, [
    artifactRecord(`sessions/${sessionId}/summary.json`, "summary")
  ]);

  const missing = await createArtifactStore({ ARTIFACTS_BUCKET: bucketFor([publication.generationManifest]) })
    .verifyManifest(publication.manifest, { r2Only: true });
  assert.equal(missing.reason, "missing_active_pointer");

  const invalidPointer = await record(publication.pointer.path, "active", {
    schema_version: 1,
    session_id: sessionId,
    artifact_base_path: `sessions/${sessionId}/generations/not-a-checksum`,
    manifest: { size_bytes: publication.manifest.size_bytes, checksum: publication.manifest.checksum }
  });
  const invalid = await createArtifactStore({ ARTIFACTS_BUCKET: bucketFor([invalidPointer]) })
    .verifyManifest(publication.manifest, { r2Only: true });
  assert.equal(invalid.reason, "invalid_active_pointer");

  const wrongGeneration = await record(publication.pointer.path, "active", {
    schema_version: 1,
    session_id: sessionId,
    artifact_base_path: `sessions/${sessionId}/generations/${"e".repeat(64)}`,
    manifest: { size_bytes: publication.manifest.size_bytes, checksum: publication.manifest.checksum }
  });
  const wrongGenerationResult = await createArtifactStore({ ARTIFACTS_BUCKET: bucketFor([wrongGeneration]) })
    .verifyManifest(publication.manifest, { r2Only: true });
  assert.equal(wrongGenerationResult.reason, "invalid_active_pointer");

  const mismatchedPointer = await record(publication.pointer.path, "active", {
    schema_version: 1,
    session_id: sessionId,
    artifact_base_path: `sessions/${sessionId}/generations/${"f".repeat(64)}`,
    manifest: { size_bytes: publication.manifest.size_bytes, checksum: `sha256:${"f".repeat(64)}` }
  });
  const mismatched = await createArtifactStore({ ARTIFACTS_BUCKET: bucketFor([mismatchedPointer]) })
    .verifyManifest(publication.manifest, { r2Only: true });
  assert.equal(mismatched.reason, "active_manifest_mismatch");
});

test("manifest verification rejects missing, corrupt, or structurally invalid manifests", async () => {
  const sessionId = "2026-09-r";
  const validSections = [artifactRecord(`sessions/${sessionId}/summary.json`, "summary")];
  const publication = await publicationFor(sessionId, validSections);

  const missing = await createArtifactStore({ ARTIFACTS_BUCKET: bucketFor([publication.pointer]) })
    .verifyManifest(publication.manifest, { r2Only: true });
  assert.equal(missing.reason, "missing");

  const corruptBytes = Uint8Array.from(publication.generationManifest.bytes);
  corruptBytes[0] ^= 1;
  const corruptManifest = { ...publication.generationManifest, bytes: corruptBytes };
  const corrupt = await createArtifactStore({ ARTIFACTS_BUCKET: bucketFor([publication.pointer, corruptManifest]) })
    .verifyManifest(publication.manifest, { r2Only: true });
  assert.equal(corrupt.reason, "checksum_mismatch");

  const cases = [
    {
      sections: validSections,
      manifestSessionId: "2026-08-r",
      reason: "invalid_manifest"
    },
    {
      sections: [
        artifactRecord(`sessions/${sessionId}/summary.json`, "summary"),
        artifactRecord(`sessions/${sessionId}/../secret.json`, "laps")
      ],
      reason: "invalid_manifest_section"
    },
    {
      sections: [validSections[0], validSections[0]],
      reason: "invalid_manifest_section"
    },
    {
      sections: [artifactRecord(`sessions/${sessionId}/laps.json`, "laps")],
      reason: "manifest_missing_summary"
    }
  ];
  for (const testCase of cases) {
    const invalidPublication = await publicationFor(
      sessionId,
      testCase.sections,
      testCase.manifestSessionId
    );
    const result = await createArtifactStore({
      ARTIFACTS_BUCKET: bucketFor([invalidPublication.pointer, invalidPublication.generationManifest])
    }).verifyManifest(invalidPublication.manifest, { r2Only: true });
    assert.equal(result.reason, testCase.reason);
  }
});

test("canonical session URLs switch only when the active generation pointer changes", async () => {
  const sessionId = "2026-09-r";
  const canonical = await record(`sessions/${sessionId}/summary.json`, "summary", { meeting: "old" });
  const generationPath = `sessions/${sessionId}/generations/${"a".repeat(64)}`;
  const generated = await record(`${generationPath}/summary.json`, "summary", { meeting: "new" });
  const pointer = await record(`sessions/${sessionId}/active.json`, "active", {
    schema_version: 1,
    session_id: sessionId,
    artifact_base_path: generationPath,
    manifest: { size_bytes: 2, checksum: `sha256:${"a".repeat(64)}` }
  });

  const beforeSwitch = await createArtifactStore({ ARTIFACTS_BUCKET: bucketFor([canonical, generated]) })
    .get(canonical.path);
  const afterSwitch = await createArtifactStore({ ARTIFACTS_BUCKET: bucketFor([canonical, generated, pointer]) })
    .get(canonical.path);

  assert.deepEqual(await beforeSwitch.json(), { meeting: "old" });
  assert.deepEqual(await afterSwitch.json(), { meeting: "new" });
});
