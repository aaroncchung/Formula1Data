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
  assert.match(job.error_message, /GitHub dispatch configuration/);
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

test("queue dispatch triggers GitHub repository dispatch when configured", async () => {
  const repository = freshRepository();
  const artifacts = { head: async () => null };
  const messages = [];
  const queue = { send: async (message) => messages.push(message) };
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    return new Response(null, { status: 204 });
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
        GITHUB_DISPATCH_TOKEN: "github-token",
        GITHUB_REPO_OWNER: "Ntrxi",
        GITHUB_REPO_NAME: "Formula1Data",
        GITHUB_DISPATCH_EVENT: "ingest_session"
      },
      repository
    );

    const job = await repository.getJob(result.job.job_id);
    assert.equal(job.status, "running");
    assert.equal(job.attempts, 1);
    assert.equal(job.error_message, null);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, "https://api.github.com/repos/Ntrxi/Formula1Data/dispatches");
    assert.equal(requests[0].init.method, "POST");
    assert.equal(requests[0].init.headers.authorization, "Bearer github-token");
    assert.equal(requests[0].init.headers["user-agent"], "formula-1-data-worker");
    assert.deepEqual(JSON.parse(requests[0].init.body), {
      event_type: "ingest_session",
      client_payload: {
        message: messages[0]
      }
    });
  } finally {
    globalThis.fetch = previousFetch;
  }
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

test("permanent GitHub dispatch failures mark the job and session failed", async () => {
  const repository = freshRepository();
  const artifacts = { head: async () => null };
  const messages = [];
  const queue = { send: async (message) => messages.push(message) };
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, { status: 401 });

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
        GITHUB_DISPATCH_TOKEN: "invalid-token",
        GITHUB_REPO_OWNER: "Ntrxi",
        GITHUB_REPO_NAME: "Formula1Data"
      },
      repository
    );

    const job = await repository.getJob(result.job.job_id);
    assert.equal(job.status, "failed");
    assert.match(job.error_message, /returned 401/);
    const status = await resolveSessionStatus({ repository, artifacts, year: 2026, round: 8, session: "R" });
    assert.equal(status.status, "failed");
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("queue messages cannot dispatch a missing job", async () => {
  const repository = freshRepository();
  await assert.rejects(
    dispatchQueueMessage(
      {
        version: 1,
        job_id: "ingest_session:2026-08-r:20260704:missing",
        kind: "ingest_session",
        session_id: "2026-08-r",
        year: 2026,
        round: 8,
        session: "R",
        artifact_base_path: "sessions/2026-08-r"
      },
      {},
      repository
    ),
    /unknown job/
  );
});

test("stale active jobs and sessions are failed for later retry", async () => {
  const repository = freshRepository();
  await repository.upsertSession({
    session_id: "2026-08-r",
    year: 2026,
    round: 8,
    session_type: "R",
    status: "ingesting"
  });
  await repository.createJob({
    job_id: "stale-job",
    session_id: "2026-08-r",
    kind: "ingest_session",
    status: "running",
    attempts: 1,
    created_at: "2026-07-04T10:00:00.000Z",
    started_at: "2026-07-04T10:01:00.000Z"
  });

  const count = await repository.failStaleJobs(
    "2026-07-04T12:00:00.000Z",
    "Ingestion timed out"
  );

  assert.equal(count, 1);
  assert.equal((await repository.getJob("stale-job")).status, "failed");
  assert.equal((await repository.getSession("2026-08-r")).status, "failed");
});
