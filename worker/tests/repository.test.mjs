import assert from "node:assert/strict";
import test from "node:test";

import { createMemoryRepository } from "../src/repository.mjs";

// Regression test for finding F-17: the default argument referenced an undefined
// `memoryState`, so calling the factory with no arguments threw a ReferenceError.
test("createMemoryRepository() works without arguments", async () => {
  const repository = createMemoryRepository();

  assert.equal(await repository.getSession("2026-09-r"), null);
  await repository.upsertSession({ session_id: "2026-09-r", year: 2026, round: 9, session_type: "R" });
  assert.equal((await repository.getSession("2026-09-r")).session_id, "2026-09-r");
  assert.equal((await repository.getSessionByLookup(2026, 9, "r")).session_id, "2026-09-r");
});

test("each createMemoryRepository() call gets its own state", async () => {
  const first = createMemoryRepository();
  const second = createMemoryRepository();

  await first.createJob({ job_id: "job-1", session_id: "2026-09-r", kind: "ingest", status: "queued" });

  assert.equal((await first.getJob("job-1")).job_id, "job-1");
  assert.equal(await second.getJob("job-1"), null);
});

test("createMemoryRepository() still honours explicit state", async () => {
  const state = {
    sessions: new Map(),
    jobs: new Map(),
    artifacts: new Map(),
    liveSnapshots: new Map()
  };
  const repository = createMemoryRepository(state);

  await repository.createJob({ job_id: "job-2", session_id: "2026-09-r", kind: "ingest", status: "queued" });

  assert.equal(state.jobs.get("job-2").job_id, "job-2");
});
