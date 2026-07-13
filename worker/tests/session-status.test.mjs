import assert from "node:assert/strict";
import test from "node:test";

import { createMemoryRepository } from "../src/repository.mjs";
import { enqueueIngestionJob, resolveSessionStatus } from "../src/session-status.mjs";

function freshRepository() {
  return createMemoryRepository({
    sessions: new Map(),
    jobs: new Map(),
    artifacts: new Map(),
    liveSnapshots: new Map()
  });
}

test("enqueueIngestionJob reuses active jobs for the same session", async () => {
  const repository = freshRepository();
  const artifacts = { head: async () => null };
  const messages = [];
  const queue = { send: async (message) => messages.push(message) };

  const first = await enqueueIngestionJob({
    repository,
    artifacts,
    queue,
    year: 2026,
    round: 8,
    session: "R",
    now: new Date("2026-07-04T12:00:00Z")
  });
  const second = await enqueueIngestionJob({
    repository,
    artifacts,
    queue,
    year: 2026,
    round: 8,
    session: "Race",
    now: new Date("2026-07-04T12:00:01Z")
  });

  assert.equal(first.action, "queued");
  assert.equal(second.action, "reused");
  assert.equal(second.job.job_id, first.job.job_id);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].session_id, "2026-08-r");
});

test("resolveSessionStatus reports ready when a manifest artifact exists", async () => {
  const repository = freshRepository();
  const artifacts = {
    head: async (path) =>
      path.endsWith("manifest.json")
        ? { key: path, size: 512, uploaded: "2026-07-04T12:00:00Z" }
        : null
  };
  const queue = { send: async () => undefined };

  const result = await enqueueIngestionJob({
    repository,
    artifacts,
    queue,
    year: 2026,
    round: 1,
    session: "R"
  });
  const status = await resolveSessionStatus({ repository, artifacts, year: 2026, round: 1, session: "R" });

  assert.equal(result.action, "ready");
  assert.equal(status.status, "ready");
  assert.equal(status.artifact_path, "sessions/2026-01-r/manifest.json");
});

test("resolveSessionStatus avoids redundant D1-style writes for an unchanged ready session", async () => {
  const repository = freshRepository();
  await repository.upsertSession({
    session_id: "2026-01-r",
    year: 2026,
    round: 1,
    meeting_id: null,
    meeting_name: null,
    session_type: "R",
    scheduled_start: null,
    status: "ready",
    artifact_base_path: "sessions/2026-01-r",
    generated_at: "2026-07-04T12:00:00Z",
    source: "r2"
  });
  let writes = 0;
  const countingRepository = {
    ...repository,
    async upsertSession(session) {
      writes += 1;
      return repository.upsertSession(session);
    }
  };
  let headCalls = 0;
  const artifacts = {
    async head(path) {
      headCalls += 1;
      return { key: path, size: 512, uploaded: "2026-07-04T12:00:00Z" };
    }
  };

  const status = await resolveSessionStatus({
    repository: countingRepository,
    artifacts,
    year: 2026,
    round: 1,
    session: "R"
  });

  assert.equal(status.status, "ready");
  assert.equal(writes, 0);
  assert.equal(headCalls, 1);
});

test("a D1-ready session with no manifest or summary becomes stale", async () => {
  const repository = freshRepository();
  await repository.upsertSession({
    session_id: "2026-09-r",
    year: 2026,
    round: 9,
    session_type: "R",
    status: "ready",
    artifact_base_path: "sessions/2026-09-r",
    source: "r2"
  });

  const status = await resolveSessionStatus({
    repository,
    artifacts: { head: async () => null },
    year: 2026,
    round: 9,
    session: "R"
  });

  assert.equal(status.status, "stale");
  assert.equal(status.artifact_exists, false);
  assert.equal((await repository.getSession("2026-09-r")).status, "stale");
});

test("optional missing sections remain a ready quality condition", async () => {
  const repository = freshRepository();
  await repository.upsertSession({
    session_id: "2026-09-r",
    year: 2026,
    round: 9,
    session_type: "R",
    status: "ready",
    artifact_base_path: "sessions/2026-09-r",
    source: "r2",
    quality_json: JSON.stringify({ status: "partial", missing_sections: ["weather"] })
  });
  const status = await resolveSessionStatus({
    repository,
    artifacts: {
      head: async (path) =>
        path.endsWith("manifest.json") ? { key: path, size: 42, uploaded: null } : null
    },
    year: 2026,
    round: 9,
    session: "R"
  });

  assert.equal(status.status, "ready");
  assert.deepEqual(status.quality, { status: "partial", missing_sections: ["weather"] });
});
