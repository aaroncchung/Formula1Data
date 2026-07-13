import assert from "node:assert/strict";
import test from "node:test";

import { applyIngestionJobUpdate } from "../src/index.mjs";
import { createMemoryRepository } from "../src/repository.mjs";

function freshRepository() {
  return createMemoryRepository({
    sessions: new Map(),
    jobs: new Map(),
    artifacts: new Map(),
    liveSnapshots: new Map()
  });
}

async function seededRepository() {
  const repository = freshRepository();
  await repository.upsertSession({
    session_id: "2026-09-r",
    year: 2026,
    round: 9,
    session_type: "R",
    status: "ingesting",
    artifact_base_path: "sessions/2026-09-r"
  });
  await repository.createJob({
    job_id: "job-1",
    session_id: "2026-09-r",
    kind: "ingest_session",
    status: "running",
    attempts: 1,
    created_at: "2026-07-13T12:00:00Z"
  });
  return repository;
}

const manifest = {
  kind: "manifest",
  path: "sessions/2026-09-r/manifest.json",
  size_bytes: 123,
  checksum: `sha256:${"a".repeat(64)}`,
  generated_at: "2026-07-13T12:10:00Z"
};

test("succeeded callbacks require a manifest record", async () => {
  await assert.rejects(
    applyIngestionJobUpdate({
      repository: await seededRepository(),
      artifacts: { verify: async () => ({ verified: true }) },
      jobId: "job-1",
      payload: { status: "succeeded", artifacts: [] }
    }),
    /require a manifest record/
  );
});

test("a manifest belonging to another session is rejected", async () => {
  await assert.rejects(
    applyIngestionJobUpdate({
      repository: await seededRepository(),
      artifacts: { verify: async () => ({ verified: true }) },
      jobId: "job-1",
      payload: {
        status: "succeeded",
        manifest: { ...manifest, path: "sessions/2026-08-r/manifest.json" },
        artifacts: []
      }
    }),
    /manifest path must belong/
  );
});

test("manifest checksum and size formats are validated", async () => {
  await assert.rejects(
    applyIngestionJobUpdate({
      repository: await seededRepository(),
      artifacts: { verify: async () => ({ verified: true }) },
      jobId: "job-1",
      payload: {
        status: "succeeded",
        manifest: { ...manifest, size_bytes: "123", checksum: "sha256:not-a-digest" },
        artifacts: []
      }
    }),
    /size_bytes must be a non-negative integer/
  );
  await assert.rejects(
    applyIngestionJobUpdate({
      repository: await seededRepository(),
      artifacts: { verify: async () => ({ verified: true }) },
      jobId: "job-1",
      payload: {
        status: "succeeded",
        manifest: { ...manifest, checksum: "sha256:not-a-digest" },
        artifacts: []
      }
    }),
    /checksum must be a lowercase sha256 checksum/
  );
});

test("verified publication failure leaves both job and session failed", async () => {
  const repository = await seededRepository();
  await assert.rejects(
    applyIngestionJobUpdate({
      repository,
      artifacts: { verify: async () => ({ verified: false, reason: "checksum_mismatch" }) },
      jobId: "job-1",
      payload: { status: "succeeded", manifest, artifacts: [] }
    }),
    /publication verification failed/i
  );
  assert.equal((await repository.getJob("job-1")).status, "failed");
  assert.equal((await repository.getSession("2026-09-r")).status, "failed");
});

test("a verified compact callback records quality without telemetry lap rows", async () => {
  const repository = await seededRepository();
  const response = await applyIngestionJobUpdate({
    repository,
    artifacts: { verify: async () => ({ verified: true, source: "r2" }) },
    jobId: "job-1",
    payload: {
      status: "succeeded",
      manifest,
      artifacts: [
        {
          kind: "summary",
          path: "sessions/2026-09-r/summary.json",
          size_bytes: 10,
          checksum: `sha256:${"b".repeat(64)}`
        },
        {
          kind: "telemetry-index",
          path: "sessions/2026-09-r/telemetry/index.json",
          size_bytes: 20,
          checksum: `sha256:${"c".repeat(64)}`,
          metadata: { lap_file_count: 500, sample_count: 100000 }
        }
      ],
      quality: {
        status: "partial",
        missing_sections: ["weather"],
        available_sections: ["summary", "telemetry-index"]
      }
    }
  });
  assert.equal(response.status, 200);
  assert.equal((await repository.getJob("job-1")).status, "succeeded");
  const session = await repository.getSession("2026-09-r");
  assert.equal(session.status, "ready");
  assert.equal(JSON.parse(session.quality_json).status, "partial");
});
