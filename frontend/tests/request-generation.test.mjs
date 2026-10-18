import assert from "node:assert/strict";
import test from "node:test";

import {
  createOrderedRunner,
  createRequestGenerationGuard
} from "../src/lib/request-generation.ts";

/** A promise plus the handles to settle it, so a test can control ordering. */
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test("a teardown invalidates an in-flight request without issuing a token", () => {
  const requests = createRequestGenerationGuard();
  const inFlight = requests.begin();

  requests.invalidate();

  assert.equal(requests.isCurrent(inFlight), false);
});

test("a newer queue or status request supersedes an older response", () => {
  const requests = createRequestGenerationGuard();
  const statusRequest = requests.begin();
  const queueRequest = requests.begin();

  assert.equal(requests.isCurrent(statusRequest), false);
  assert.equal(requests.isCurrent(queueRequest), true);
});

// The ordering case the guard exists for: a poll that started earlier resolves
// later. Arrival order must not decide which response writes state.
test("a slow earlier poll cannot overwrite a newer response", () => {
  const requests = createRequestGenerationGuard();
  const slowPoll = requests.begin();
  const fastPoll = requests.begin();

  assert.equal(requests.isCurrent(fastPoll), true);
  assert.equal(requests.isCurrent(slowPoll), false);
});

test("each guard tracks its own generation", () => {
  const statusRequests = createRequestGenerationGuard();
  const otherRequests = createRequestGenerationGuard();
  const statusToken = statusRequests.begin();

  otherRequests.begin();

  assert.equal(statusRequests.isCurrent(statusToken), true);
});

// The bug this exists for, reproduced directly: `SessionIngestionPanel` polls
// status every 3 s against a 12 s timeout, so a poll that started earlier can
// resolve later. Arrival order must not decide which response writes state.
test("a poll that starts first but finishes last does not commit", async () => {
  const runner = createOrderedRunner();
  const slow = deferred();
  const fast = deferred();
  const committed = [];
  const handlers = { onResult: (value) => committed.push(value), onError: () => {} };

  const slowRun = runner.run(() => slow.promise, handlers);
  const fastRun = runner.run(() => fast.promise, handlers);

  fast.resolve("ready");
  await fastRun;
  slow.resolve("queued");
  await slowRun;

  assert.deepEqual(committed, ["ready"]);
});

test("a superseded rejection does not overwrite a newer success with an error", async () => {
  const runner = createOrderedRunner();
  const slow = deferred();
  const fast = deferred();
  const committed = [];
  const errors = [];
  const handlers = {
    onResult: (value) => committed.push(value),
    onError: (error) => errors.push(error)
  };

  const slowRun = runner.run(() => slow.promise, handlers);
  const fastRun = runner.run(() => fast.promise, handlers);

  fast.resolve("ready");
  await fastRun;
  slow.reject(new Error("stale failure"));
  await slowRun;

  assert.deepEqual(committed, ["ready"]);
  assert.deepEqual(errors, []);
});

test("the newest call still commits normally", async () => {
  const runner = createOrderedRunner();
  const committed = [];

  const value = await runner.run(async () => "ready", {
    onResult: (result) => committed.push(result),
    onError: () => {}
  });

  assert.deepEqual(committed, ["ready"]);
  assert.equal(value, "ready");
});

test("an error from the newest call is reported", async () => {
  const runner = createOrderedRunner();
  const errors = [];

  const value = await runner.run(
    async () => {
      throw new Error("api down");
    },
    { onResult: () => {}, onError: (error) => errors.push(error.message) }
  );

  assert.deepEqual(errors, ["api down"]);
  assert.equal(value, null);
});

test("retiring the runner drops a response that is already in flight", async () => {
  // What the effect cleanup does on unmount, or when the panel moves to a
  // different session: a late response must not describe a session the user
  // has already left.
  const runner = createOrderedRunner();
  const inFlight = deferred();
  const committed = [];

  const run = runner.run(() => inFlight.promise, {
    onResult: (value) => committed.push(value),
    onError: () => {}
  });
  runner.retire();
  inFlight.resolve("ready");

  assert.equal(await run, null);
  assert.deepEqual(committed, []);
});
