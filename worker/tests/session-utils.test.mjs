import assert from "node:assert/strict";
import test from "node:test";

import {
  artifactBasePath,
  normalizeSessionCode,
  sanitizeArtifactPath,
  sessionIdFromParts
} from "../src/session-utils.mjs";

test("normalizes session identifiers and artifact paths", () => {
  assert.equal(normalizeSessionCode("Sprint Shootout"), "SQ");
  assert.equal(normalizeSessionCode("q"), "Q");
  assert.equal(sessionIdFromParts(2026, 3, "Race"), "2026-03-r");
  assert.equal(artifactBasePath("2026-03-r"), "sessions/2026-03-r");
  assert.equal(sanitizeArtifactPath("/data/sessions/2026-03-r/summary.json"), "sessions/2026-03-r/summary.json");
  assert.throws(() => sanitizeArtifactPath("/data/../secret.json"), /parent directory/);
});
