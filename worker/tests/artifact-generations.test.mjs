import assert from "node:assert/strict";
import test from "node:test";

import { createArtifactStore } from "../src/artifact-store.mjs";

const SESSION = "2026-09-r";

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * A bucket holding one session published as a generation.
 *
 * `manifestBody` is hashed to name the generation, exactly as the publisher
 * does, so the pointer these fixtures produce is internally consistent by
 * construction rather than by a hardcoded digest that drifts.
 */
async function generationBucket({ manifestBody, pointerOverrides = {}, extra = {} } = {}) {
  const body = manifestBody ?? JSON.stringify({ session_id: SESSION, sections: [{ kind: "summary", path: `sessions/${SESSION}/summary.json` }] });
  const generationId = await sha256Hex(body);
  const base = `sessions/${SESSION}/generations/${generationId}`;
  const pointer = {
    schema_version: 1,
    session_id: SESSION,
    artifact_base_path: base,
    manifest: { size_bytes: new TextEncoder().encode(body).byteLength, checksum: `sha256:${generationId}` },
    ...pointerOverrides
  };
  const objects = {
    [`sessions/${SESSION}/active.json`]: JSON.stringify(pointer),
    [`${base}/manifest.json`]: body,
    [`${base}/summary.json`]: '{"ok":true}',
    ...extra
  };

  const reads = [];
  const bucket = {
    async get(key) {
      reads.push(key);
      if (!(key in objects)) return null;
      const text = objects[key];
      return {
        body: new Blob([text]).stream(),
        size: new TextEncoder().encode(text).byteLength,
        httpEtag: '"e"',
        uploaded: new Date("2026-07-26T00:00:00Z"),
        writeHttpMetadata(headers) {
          headers.set("content-type", "application/json");
        }
      };
    },
    async head(key) {
      reads.push(key);
      if (!(key in objects)) return null;
      const text = objects[key];
      return {
        size: new TextEncoder().encode(text).byteLength,
        httpEtag: '"e"',
        uploaded: new Date("2026-07-26T00:00:00Z")
      };
    }
  };
  return { bucket, generationId, base, body, reads, objects };
}

test("a conventional session path is served from the generation the pointer names", async () => {
  const { bucket, base, reads } = await generationBucket();
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const response = await store.get(`/data/sessions/${SESSION}/summary.json`);

  assert.equal(response.status, 200);
  assert.equal(await response.text(), '{"ok":true}');
  // The frontend asked by convention and never learns generations exist.
  assert.ok(reads.includes(`${base}/summary.json`));
  assert.ok(!reads.includes(`sessions/${SESSION}/summary.json`));
});

test("one pointer lookup serves a whole page of artifacts", async () => {
  const { bucket, reads, base, objects } = await generationBucket();
  objects[`${base}/laps.json`] = "[]";
  objects[`${base}/results.json`] = "[]";
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  await store.get(`/data/sessions/${SESSION}/summary.json`);
  await store.get(`/data/sessions/${SESSION}/laps.json`);
  await store.get(`/data/sessions/${SESSION}/results.json`);

  // Building the resolver per call instead of per store would make this 3.
  const pointerReads = reads.filter((key) => key.endsWith("active.json"));
  assert.equal(pointerReads.length, 1);
});

test("a session published before generations existed still resolves conventionally", async () => {
  const legacy = { [`sessions/${SESSION}/summary.json`]: '{"legacy":true}' };
  const bucket = {
    async get(key) {
      if (!(key in legacy)) return null;
      const text = legacy[key];
      return {
        body: new Blob([text]).stream(),
        size: text.length,
        httpEtag: '"e"',
        uploaded: new Date("2026-07-26T00:00:00Z"),
        writeHttpMetadata() {}
      };
    }
  };

  const response = await createArtifactStore({ ARTIFACTS_BUCKET: bucket }).get(
    `/data/sessions/${SESSION}/summary.json`
  );

  assert.equal(response.status, 200);
  assert.equal(await response.text(), '{"legacy":true}');
});

test("the pointer object and generation bodies are addressed directly, not resolved", async () => {
  const { bucket, base, reads } = await generationBucket();
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  await store.get(`/data/sessions/${SESSION}/active.json`);
  await store.get(`/data/${base}/summary.json`);

  // Resolving either would recurse or double-prefix the key.
  assert.ok(!reads.some((key) => key.includes("generations/") && key.includes("active.json")));
  assert.ok(!reads.some((key) => key.split("generations/").length > 2));
});

test("a malformed pointer degrades to the conventional key rather than 500ing the session", async () => {
  const { bucket, objects } = await generationBucket();
  objects[`sessions/${SESSION}/active.json`] = "{ this is not json";
  objects[`sessions/${SESSION}/summary.json`] = '{"conventional":true}';
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const response = await store.get(`/data/sessions/${SESSION}/summary.json`);

  // Failing open cannot serve the wrong generation -- a generation-published
  // session has nothing at its conventional key, so the read simply misses.
  assert.equal(response.status, 200);
  assert.equal(await response.text(), '{"conventional":true}');
});

test("an oversized pointer is refused rather than read into memory", async () => {
  const { bucket, objects } = await generationBucket();
  objects[`sessions/${SESSION}/active.json`] = "x".repeat(8 * 1024);
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const result = await store.verifyManifest({
    path: `sessions/${SESSION}/manifest.json`,
    size_bytes: 10,
    checksum: `sha256:${"0".repeat(64)}`
  });

  assert.equal(result.verified, false);
  assert.equal(result.reason, "invalid_active_pointer");
});

test("head reports whether a key resolved through a generation", async () => {
  const { bucket, base, generationId } = await generationBucket();
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const resolved = await store.head(`sessions/${SESSION}/summary.json`);

  assert.equal(resolved.key, `sessions/${SESSION}/summary.json`);
  assert.equal(resolved.storage_key, `${base}/summary.json`);
  assert.equal(resolved.source, "r2");
  assert.ok(resolved.storage_key.includes(generationId));
});

test("verifyManifest accepts the manifest the active pointer names", async () => {
  const { bucket, body, generationId, base } = await generationBucket();
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const result = await store.verifyManifest({
    path: `sessions/${SESSION}/manifest.json`,
    size_bytes: new TextEncoder().encode(body).byteLength,
    checksum: `sha256:${generationId}`
  });

  assert.equal(result.verified, true);
  assert.equal(result.generation_id, generationId);
  assert.equal(result.storage_key, `${base}/manifest.json`);
});

test("verifyManifest rejects a generation published but not yet made active", async () => {
  // The runner uploaded a new generation and the callback reports it, but the
  // pointer still names the old one. Reporting success here would mark a
  // session ready against artifacts no reader can reach.
  const { bucket } = await generationBucket();
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const result = await store.verifyManifest({
    path: `sessions/${SESSION}/manifest.json`,
    size_bytes: 999,
    checksum: `sha256:${"c".repeat(64)}`
  });

  assert.equal(result.verified, false);
  assert.equal(result.reason, "active_manifest_mismatch");
});

test("verifyManifest fails closed when no pointer exists at all", async () => {
  const bucket = { async get() { return null; } };
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const result = await store.verifyManifest({
    path: `sessions/${SESSION}/manifest.json`,
    size_bytes: 10,
    checksum: `sha256:${"0".repeat(64)}`
  });

  assert.equal(result.verified, false);
  assert.equal(result.reason, "missing_active_pointer");
});

test("verifyManifest rejects a pointer whose id and manifest checksum disagree", async () => {
  const { bucket, body, generationId } = await generationBucket({
    pointerOverrides: { manifest: { size_bytes: 4, checksum: `sha256:${"d".repeat(64)}` } }
  });
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const result = await store.verifyManifest({
    path: `sessions/${SESSION}/manifest.json`,
    size_bytes: new TextEncoder().encode(body).byteLength,
    checksum: `sha256:${generationId}`
  });

  assert.equal(result.verified, false);
  assert.equal(result.reason, "invalid_active_pointer");
});

test("verifyManifest rejects a manifest describing another session", async () => {
  const body = JSON.stringify({
    session_id: "2026-08-r",
    sections: [{ kind: "summary", path: "sessions/2026-08-r/summary.json" }]
  });
  const { bucket, generationId } = await generationBucket({ manifestBody: body });
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const result = await store.verifyManifest({
    path: `sessions/${SESSION}/manifest.json`,
    size_bytes: new TextEncoder().encode(body).byteLength,
    checksum: `sha256:${generationId}`
  });

  assert.equal(result.verified, false);
  assert.equal(result.reason, "manifest_session_mismatch");
});

test("verifyManifest rejects a manifest with a section escaping its session", async () => {
  const body = JSON.stringify({
    session_id: SESSION,
    sections: [
      { kind: "summary", path: `sessions/${SESSION}/summary.json` },
      { kind: "laps", path: `sessions/${SESSION}/../2026-08-r/laps.json` }
    ]
  });
  const { bucket, generationId } = await generationBucket({ manifestBody: body });
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const result = await store.verifyManifest({
    path: `sessions/${SESSION}/manifest.json`,
    size_bytes: new TextEncoder().encode(body).byteLength,
    checksum: `sha256:${generationId}`
  });

  assert.equal(result.verified, false);
  assert.equal(result.reason, "invalid_manifest_sections");
});

test("verifyManifest rejects a record that is not a well-formed artifact record", async () => {
  const { bucket } = await generationBucket();
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const result = await store.verifyManifest({
    path: `sessions/${SESSION}/manifest.json`,
    size_bytes: -1,
    checksum: "not-a-checksum"
  });

  assert.equal(result.verified, false);
  assert.equal(result.reason, "invalid_manifest_record");
});

test("verifyManifest refuses a path that is not a session manifest", async () => {
  const { bucket } = await generationBucket();
  const store = createArtifactStore({ ARTIFACTS_BUCKET: bucket });

  const result = await store.verifyManifest({
    path: "catalog.json",
    size_bytes: 10,
    checksum: `sha256:${"0".repeat(64)}`
  });

  assert.equal(result.verified, false);
  assert.equal(result.reason, "invalid_manifest_record");
});
