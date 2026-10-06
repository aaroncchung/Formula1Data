import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiClientError,
  createStaticApi,
  latestSession,
  SESSION_TYPE_ORDER
} from "../src/lib/static-api-core.ts";

function session(year, round, type, status = "available") {
  return {
    session_id: `${year}-${String(round).padStart(2, "0")}-${type.toLowerCase()}`,
    year,
    round,
    meeting_id: `${year}-${round}`,
    name: type,
    type,
    status,
    is_sample: false
  };
}

/** A static API over an in-memory set of artifacts; a missing path is a 404. */
function apiOver(artifacts) {
  return createStaticApi(async (path) => {
    if (!(path in artifacts)) {
      throw new ApiClientError(
        "Static artifact was not generated",
        { code: "artifact_not_found", message: "Not Found", details: { path } },
        "/data"
      );
    }
    const artifact = artifacts[path];
    if (artifact instanceof Error) {
      throw artifact;
    }
    return artifact;
  });
}

function catalog(sessions) {
  return { schema_version: 1, generated_at: "", seasons: [], meetings: [], sessions, totals: {} };
}

test("the latest session is the last one of the newest round of the newest year", () => {
  const sessions = [
    session(2026, 9, "Q"),
    session(2025, 24, "R"),
    session(2026, 9, "R"),
    session(2026, 8, "R"),
    session(2026, 9, "FP1")
  ];

  assert.equal(latestSession(sessions)?.session_id, "2026-09-r");
});

test("the session type order follows the weekend, sprint sessions included", () => {
  const ordered = ["FP1", "FP2", "FP3", "SQ", "S", "Q", "R"];

  assert.deepEqual(
    [...ordered].reverse().sort((a, b) => SESSION_TYPE_ORDER[a] - SESSION_TYPE_ORDER[b]),
    ordered
  );
});

test("no sessions means no latest session", () => {
  assert.equal(latestSession([]), undefined);
});

test("the primary session skips sessions that have no artifacts", async () => {
  const api = apiOver({
    "catalog.json": catalog([session(2026, 8, "R"), session(2026, 9, "R", "missing")])
  });

  assert.equal((await api.primarySession()).session_id, "2026-08-r");
});

test("the primary session falls back to the newest listed session when none has artifacts", async () => {
  const api = apiOver({
    "catalog.json": catalog([session(2026, 8, "R", "missing"), session(2026, 9, "R", "missing")])
  });

  assert.equal((await api.primarySession()).session_id, "2026-09-r");
});

test("an empty catalog has no primary session", async () => {
  const api = apiOver({ "catalog.json": catalog([]) });

  await assert.rejects(api.primarySession(), (error) => {
    assert.ok(error instanceof ApiClientError);
    assert.equal(error.payload.code, "artifact_not_found");
    return true;
  });
});

test("a session without a telemetry index reads as null, not as a failure", async () => {
  const api = apiOver({});

  assert.equal(await api.telemetryIndex("2026-08-r"), null);
});

test("a telemetry index that fails to load for another reason still fails", async () => {
  const unavailable = new ApiClientError(
    "Static artifact could not be loaded",
    { code: "artifact_unavailable", message: "Bad Gateway" },
    "/data"
  );
  const api = apiOver({ "sessions/2026-08-r/telemetry/index.json": unavailable });

  await assert.rejects(api.telemetryIndex("2026-08-r"), unavailable);
});

test("a telemetry comparison without an index is an empty state", async () => {
  const api = apiOver({});

  const result = await api.telemetryCompare("2026-08-r", "RUS", 10, "ANT", 10);

  assert.equal(result.reason, "No telemetry lap artifacts are available for this session.");
});
