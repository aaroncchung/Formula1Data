import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createArtifactStore } from "../src/artifact-store.mjs";
import { resolveSessionStatus } from "../src/session-status.mjs";

/**
 * Drive the Worker with objects the Python publisher actually produced.
 *
 * `backend/tests/test_generation_contract.py` writes the fixture this loads, so
 * the two sides cannot disagree about the pointer shape or the key layout while
 * both suites stay green -- which is exactly what would happen if each kept
 * using its own hand-written fixtures.
 *
 * If this file fails to load, run the Python suite first: the fixture is
 * generated, not committed by hand.
 */
const fixture = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/generation-contract.json", import.meta.url)), "utf-8")
);

const { session_id: SESSION_ID, generation_id: GENERATION_ID, objects } = fixture;

function publisherBucket({ omit = [] } = {}) {
  const present = Object.fromEntries(
    Object.entries(objects).filter(([key]) => !omit.includes(key))
  );
  const encoder = new TextEncoder();
  const toObject = (text, withBody) => ({
    ...(withBody ? { body: new Blob([text]).stream() } : {}),
    size: encoder.encode(text).byteLength,
    httpEtag: '"contract"',
    uploaded: new Date("2026-07-27T00:00:00Z"),
    writeHttpMetadata(headers) {
      headers.set("content-type", "application/json");
    }
  });
  return {
    async get(key) {
      return key in present ? toObject(present[key], true) : null;
    },
    async head(key) {
      return key in present ? toObject(present[key], false) : null;
    }
  };
}

test("the publisher's pointer resolves the publisher's generation keys", async () => {
  const store = createArtifactStore({ ARTIFACTS_BUCKET: publisherBucket() });

  const summary = await store.get(`/data/sessions/${SESSION_ID}/summary.json`);
  assert.equal(summary.status, 200);
  assert.equal(JSON.parse(await summary.text()).meeting, "Contract GP");

  // Telemetry paths are relative to the session directory, so they exercise a
  // deeper key than the flat section files do.
  const lap = await store.get(`/data/sessions/${SESSION_ID}/telemetry/ver-lap-1.json`);
  assert.equal(lap.status, 200);
  assert.deepEqual(JSON.parse(await lap.text()).speed, [1, 2, 3]);
});

test("the Worker verifies the manifest the publisher committed", async () => {
  const store = createArtifactStore({ ARTIFACTS_BUCKET: publisherBucket() });
  const manifestKey = `sessions/${SESSION_ID}/generations/${GENERATION_ID}/manifest.json`;
  const manifestText = objects[manifestKey];

  const result = await store.verifyManifest({
    path: `sessions/${SESSION_ID}/manifest.json`,
    size_bytes: new TextEncoder().encode(manifestText).byteLength,
    checksum: `sha256:${GENERATION_ID}`
  });

  assert.equal(result.verified, true, JSON.stringify(result));
  assert.equal(result.generation_id, GENERATION_ID);
  assert.equal(result.storage_key, manifestKey);
});

test("a session with no D1 row is seeded ready from the published generation", async () => {
  const upserts = [];
  const repository = {
    async getSession() {
      return null;
    },
    async upsertSession(values) {
      upserts.push(values);
      return values;
    },
    async getActiveJob() {
      return null;
    }
  };

  const status = await resolveSessionStatus({
    repository,
    artifacts: createArtifactStore({ ARTIFACTS_BUCKET: publisherBucket() }),
    year: 2026,
    round: 9,
    session: "R"
  });

  assert.equal(status.status, "ready");
  assert.equal(status.artifact_exists, true);
  // An R2-backed manifest is authoritative, so the missing row is reconciled
  // rather than left reporting "missing" until someone re-ingests.
  assert.equal(upserts.length, 1);
  assert.equal(upserts[0].status, "ready");
});

test("a static-export manifest reports ready but does not conjure a D1 row", async () => {
  const upserts = [];
  const repository = {
    async getSession() {
      return null;
    },
    async upsertSession(values) {
      upserts.push(values);
      return values;
    },
    async getActiveJob() {
      return null;
    }
  };
  // No bucket at all: the only answer comes from the committed static export.
  const env = { STATIC_DATA_BASE_URL: "https://formula1data.pages.dev/data" };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, { status: 200, headers: { "content-length": "10" } });
  try {
    const status = await resolveSessionStatus({
      repository,
      artifacts: createArtifactStore(env),
      year: 2026,
      round: 9,
      session: "R"
    });
    // Reporting is preserved -- a fallback-served deployment still works.
    assert.equal(status.status, "ready");
    assert.equal(status.artifact_exists, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
  // But nothing was written: the static export is committed data, not evidence
  // about the bucket, and a row seeded from it would later read as history.
  assert.equal(upserts.length, 0);
});

test("a session whose generation was published but never pointed at is not ready", async () => {
  // The runner uploaded the generation and then died before the flip. Every
  // body is in the bucket; nothing names it. The session must not read ready.
  const bucket = publisherBucket({ omit: [`sessions/${SESSION_ID}/active.json`] });
  const repository = {
    async getSession() {
      return null;
    },
    async upsertSession(values) {
      return values;
    },
    async getActiveJob() {
      return null;
    }
  };

  const status = await resolveSessionStatus({
    repository,
    artifacts: createArtifactStore({ ARTIFACTS_BUCKET: bucket }),
    year: 2026,
    round: 9,
    session: "R"
  });

  assert.equal(status.status, "missing");
  assert.equal(status.artifact_exists, false);
});
