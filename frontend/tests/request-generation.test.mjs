import assert from "node:assert/strict";
import test from "node:test";

import { createRequestGenerationGuard } from "../src/lib/request-generation.ts";

test("navigation invalidates an in-flight dashboard request", () => {
  const requests = createRequestGenerationGuard();
  const previousSession = requests.begin();

  requests.invalidate();

  assert.equal(requests.isCurrent(previousSession), false);
});

test("a newer queue or status request supersedes an older response", () => {
  const requests = createRequestGenerationGuard();
  const statusRequest = requests.begin();
  const queueRequest = requests.begin();

  assert.equal(requests.isCurrent(statusRequest), false);
  assert.equal(requests.isCurrent(queueRequest), true);
});
