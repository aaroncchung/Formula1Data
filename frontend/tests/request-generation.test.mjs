import assert from "node:assert/strict";
import test from "node:test";

import { createRequestGenerationGuard } from "../src/lib/request-generation.ts";

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
