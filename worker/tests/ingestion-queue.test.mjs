import assert from "node:assert/strict";
import test from "node:test";

import { dispatchQueueMessage } from "../src/index.mjs";
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

test("queue dispatch fails the job and session when no ingestion webhook is configured", async () => {
  const repository = freshRepository();
  const artifacts = { head: async () => null };
  const messages = [];
  const queue = { send: async (message) => messages.push(message) };

  const result = await enqueueIngestionJob({
    repository,
    artifacts,
    queue,
    year: 2026,
    round: 8,
    session: "R",
    now: new Date("2026-07-04T12:00:00Z")
  });

  await dispatchQueueMessage(messages[0], {}, repository);

  const job = await repository.getJob(result.job.job_id);
  assert.equal(job.status, "failed");
  assert.equal(job.attempts, 1);
  assert.match(job.error_message, /INGESTION_WEBHOOK_URL/);
  assert.match(job.error_message, /external Python ingestion runner/);
  assert.ok(job.finished_at);

  const status = await resolveSessionStatus({ repository, artifacts, year: 2026, round: 8, session: "Race" });
  assert.equal(status.status, "failed");
  assert.equal(status.job.job_id, job.job_id);
  assert.equal(status.job.error_message, job.error_message);

  const retry = await enqueueIngestionJob({
    repository,
    artifacts,
    queue,
    year: 2026,
    round: 8,
    session: "R",
    now: new Date("2026-07-04T12:00:01Z")
  });
  assert.equal(retry.action, "queued");
  assert.notEqual(retry.job.job_id, job.job_id);
  assert.equal(messages.length, 2);
});

test("queue dispatch posts to a configured ingestion webhook and leaves callback completion unchanged", async () => {
  const repository = freshRepository();
  const artifacts = { head: async () => null };
  const messages = [];
  const queue = { send: async (message) => messages.push(message) };
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    return new Response(null, { status: 202 });
  };

  try {
    const result = await enqueueIngestionJob({
      repository,
      artifacts,
      queue,
      year: 2026,
      round: 8,
      session: "R",
      now: new Date("2026-07-04T12:00:00Z")
    });

    await dispatchQueueMessage(
      messages[0],
      {
        INGESTION_WEBHOOK_URL: "https://runner.example.com/jobs",
        INGESTION_WEBHOOK_TOKEN: "secret"
      },
      repository
    );

    const job = await repository.getJob(result.job.job_id);
    assert.equal(job.status, "running");
    assert.equal(job.attempts, 1);
    assert.equal(job.error_message, null);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, "https://runner.example.com/jobs");
    assert.equal(requests[0].init.method, "POST");
    assert.equal(requests[0].init.headers.get("authorization"), "Bearer secret");
    assert.deepEqual(JSON.parse(requests[0].init.body), messages[0]);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
