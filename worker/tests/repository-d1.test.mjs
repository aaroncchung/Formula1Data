import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createD1Repository } from "../src/repository.mjs";
import { enqueueIngestionJob, INGEST_SESSION } from "../src/session-status.mjs";

// Every other Worker test uses createMemoryRepository, so none of the SQL in
// repository.mjs is exercised anywhere -- not the db.batch in
// transitionJobAndSession, not the `on conflict` upserts, and not the partial
// unique index from migrations/0002. That index is what makes createJob return
// null on a duplicate active job, which is the only way the recovery branch in
// enqueueIngestionJob is reachable. The in-memory createJob always succeeds, so
// that branch could never run under test.
//
// node:sqlite is unflagged on Node 24 but requires --experimental-sqlite on
// Node 22. Skip rather than fail so the suite stays runnable on either.
let DatabaseSync = null;
let sqliteUnavailable = null;
try {
  ({ DatabaseSync } = await import("node:sqlite"));
} catch (error) {
  sqliteUnavailable = `node:sqlite is unavailable (${error.message})`;
}

const MIGRATIONS_DIR = fileURLToPath(new URL("../../migrations/", import.meta.url));

/** Apply every checked-in migration, in filename order, to a fresh database. */
function migratedDatabase() {
  const database = new DatabaseSync(":memory:");
  for (const name of readdirSync(MIGRATIONS_DIR).filter((f) => f.endsWith(".sql")).sort()) {
    database.exec(readFileSync(MIGRATIONS_DIR + name, "utf8"));
  }
  return database;
}

/**
 * Minimal D1 binding over node:sqlite.
 *
 * Covers exactly the surface repository.mjs uses: prepare().bind() returning a
 * new statement, first()/all()/run(), and batch() as one transaction. Async to
 * match D1, which repository.mjs awaits throughout.
 */
function d1(database) {
  const statement = (sql, params = []) => ({
    bind: (...values) => statement(sql, values.map((v) => (v === undefined ? null : v))),
    first: async () => database.prepare(sql).get(...params) ?? null,
    all: async () => ({ results: database.prepare(sql).all(...params), success: true }),
    run: async () => ({ ...database.prepare(sql).run(...params), success: true }),
    _apply: () => database.prepare(sql).run(...params),
  });
  return {
    prepare: (sql) => statement(sql),
    batch: async (statements) => {
      database.exec("begin");
      try {
        const results = statements.map((entry) => entry._apply());
        database.exec("commit");
        return results.map((meta) => ({ ...meta, success: true }));
      } catch (error) {
        database.exec("rollback");
        throw error;
      }
    },
  };
}

const SESSION_ID = "2026-09-r";

function newSession(overrides = {}) {
  return {
    session_id: SESSION_ID,
    year: 2026,
    round: 9,
    meeting_id: "2026-09-example",
    meeting_name: "Example Grand Prix",
    session_type: "R",
    scheduled_start: "2026-07-05T13:00:00Z",
    status: "queued",
    artifact_base_path: `sessions/${SESSION_ID}`,
    generated_at: null,
    source: "dynamic",
    quality_json: null,
    ...overrides,
  };
}

function newJob(overrides = {}) {
  return {
    job_id: "ingest_session:2026-09-r:20260705120000000:aaaaaaaa",
    session_id: SESSION_ID,
    kind: INGEST_SESSION,
    status: "queued",
    attempts: 0,
    error_message: null,
    created_at: "2026-07-05T12:00:00.000Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

function repositoryFixture() {
  const database = migratedDatabase();
  return { database, repository: createD1Repository(d1(database)) };
}

const options = sqliteUnavailable ? { skip: sqliteUnavailable } : {};

test("migrations apply cleanly and create the expected schema", options, () => {
  const database = migratedDatabase();
  const tables = database
    .prepare("select name from sqlite_master where type = 'table' order by name")
    .all()
    .map((row) => row.name);
  assert.deepEqual(tables, ["artifacts", "ingestion_jobs", "live_snapshots", "sessions"]);

  // 0003 adds these; a repository write below depends on both.
  const sessionColumns = database.prepare("pragma table_info(sessions)").all().map((c) => c.name);
  const artifactColumns = database.prepare("pragma table_info(artifacts)").all().map((c) => c.name);
  assert.ok(sessionColumns.includes("quality_json"));
  assert.ok(artifactColumns.includes("metadata_json"));
});

test("upsertSession inserts, then coalesces null metadata instead of erasing it", options, async () => {
  const { repository } = repositoryFixture();

  const inserted = await repository.upsertSession(newSession());
  assert.equal(inserted.session_id, SESSION_ID);
  assert.equal(inserted.meeting_name, "Example Grand Prix");
  assert.equal(inserted.status, "queued");

  // The status-resolution path re-upserts with nulls for metadata it does not
  // know; the `coalesce(excluded.x, sessions.x)` columns must survive that.
  const updated = await repository.upsertSession(
    newSession({ meeting_id: null, meeting_name: null, scheduled_start: null, status: "ready" })
  );
  assert.equal(updated.status, "ready");
  assert.equal(updated.meeting_id, "2026-09-example");
  assert.equal(updated.meeting_name, "Example Grand Prix");
  assert.equal(updated.scheduled_start, "2026-07-05T13:00:00Z");
});

test("transitionJobAndSession commits both rows in one batch", options, async () => {
  const { repository } = repositoryFixture();
  await repository.upsertSession(newSession());
  await repository.createJob(newJob({ status: "running" }));

  const transition = await repository.transitionJobAndSession(
    newJob().job_id,
    { status: "succeeded", finished_at: "2026-07-05T12:30:00.000Z", error_message: null },
    { session_id: SESSION_ID, status: "ready", generated_at: "2026-07-05T12:30:00.000Z" }
  );

  assert.equal(transition.job.status, "succeeded");
  assert.equal(transition.session.status, "ready");
  assert.equal(transition.session.generated_at, "2026-07-05T12:30:00.000Z");
});

test("recordArtifacts upserts on the (session_id, kind, path) primary key", options, async () => {
  const { repository, database } = repositoryFixture();
  await repository.upsertSession(newSession());

  const artifact = {
    kind: "manifest",
    path: `sessions/${SESSION_ID}/manifest.json`,
    size_bytes: 10,
    checksum: `sha256:${"a".repeat(64)}`,
    generated_at: "2026-07-05T12:30:00.000Z",
    metadata: { lap_count: 1 },
  };
  await repository.recordArtifacts(SESSION_ID, [artifact]);
  await repository.recordArtifacts(SESSION_ID, [{ ...artifact, size_bytes: 20, metadata: { lap_count: 2 } }]);

  // Re-recording the same path must update in place, not insert a second row.
  const rows = database.prepare("select * from artifacts where session_id = ?").all(SESSION_ID);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].size_bytes, 20);
  assert.equal(rows[0].metadata_json, JSON.stringify({ lap_count: 2 }));
});

test("failStaleJobs fails only jobs older than the cutoff, and their sessions", options, async () => {
  const { repository, database } = repositoryFixture();
  await repository.upsertSession(newSession({ status: "ingesting" }));
  await repository.createJob(newJob({ status: "running", started_at: "2026-07-05T10:00:00.000Z" }));

  const failedCount = await repository.failStaleJobs(
    "2026-07-05T11:00:00.000Z",
    "Ingestion did not complete within 120 minutes"
  );
  assert.equal(failedCount, 1);

  const job = await repository.getJob(newJob().job_id);
  assert.equal(job.status, "failed");
  assert.equal(job.error_message, "Ingestion did not complete within 120 minutes");
  assert.equal((await repository.getSession(SESSION_ID)).status, "failed");

  // A fresh job must be left alone.
  database.exec("update ingestion_jobs set status = 'queued', started_at = '2026-07-05T23:00:00.000Z'");
  assert.equal(await repository.failStaleJobs("2026-07-05T11:00:00.000Z", "stale"), 0);
});

test("the 0002 partial unique index makes createJob return null for a duplicate active job", options, async () => {
  const { repository } = repositoryFixture();
  await repository.upsertSession(newSession());

  const first = await repository.createJob(newJob());
  assert.equal(first.job_id, newJob().job_id);

  // `insert or ignore` + the partial unique index on (session_id, kind) where
  // status in ('queued','running'): the second active job is silently dropped,
  // so getJob on the new id returns null. That null is what drives the recovery
  // branch in enqueueIngestionJob.
  const duplicate = await repository.createJob(newJob({ job_id: "ingest_session:2026-09-r:20260705120001000:bbbbbbbb" }));
  assert.equal(duplicate, null);

  const active = await repository.getActiveJob(SESSION_ID, INGEST_SESSION);
  assert.equal(active.job_id, newJob().job_id);

  // Once the first job reaches a terminal state the index no longer applies.
  await repository.updateJob(newJob().job_id, { status: "failed" });
  const replacement = await repository.createJob(
    newJob({ job_id: "ingest_session:2026-09-r:20260705120002000:cccccccc" })
  );
  assert.equal(replacement.job_id, "ingest_session:2026-09-r:20260705120002000:cccccccc");
});

test("a forced re-enqueue against real SQL reuses the active job instead of duplicating it", options, async () => {
  const { repository } = repositoryFixture();
  const artifacts = { head: async () => null };
  const sent = [];
  const queue = { send: async (message) => sent.push(message) };
  const lookup = { year: 2026, round: 9, session: "R" };

  const queued = await enqueueIngestionJob({ repository, artifacts, queue, ...lookup });
  assert.equal(queued.action, "queued");
  assert.equal(sent.length, 1);

  // force skips both early-return guards in enqueueIngestionJob, so this call
  // reaches createJob -- exactly the path the UI's "Retry ingestion" button
  // takes. Without migration 0002 it would open a second active job for the
  // same session; with it, createJob returns null and the recovery branch
  // hands back the job already in flight.
  const forced = await enqueueIngestionJob({ repository, artifacts, queue, ...lookup, force: true });
  assert.equal(forced.action, "reused");
  assert.equal(forced.job.job_id, queued.job.job_id);
  assert.equal(sent.length, 1, "the reused path must not enqueue a second message");
});
