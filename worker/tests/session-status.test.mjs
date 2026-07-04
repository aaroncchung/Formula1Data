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
