import assert from "node:assert/strict";
import test from "node:test";

import { fetchArtifactResponse, resolveArtifactBaseUrl } from "../src/lib/artifact-source.ts";
import { createStaticApi } from "../src/lib/static-api-core.ts";

test("production artifacts resolve through the Worker data boundary", () => {
  assert.equal(
    resolveArtifactBaseUrl({ dynamicApiBaseUrl: "https://formula-1-data-api.example.workers.dev/" }),
    "https://formula-1-data-api.example.workers.dev/data"
  );
  assert.equal(
    resolveArtifactBaseUrl({
      artifactBaseUrl: "https://artifacts.example/data/",
      dynamicApiBaseUrl: "https://ignored.example"
    }),
    "https://artifacts.example/data"
  );
});

test("offline mode continues to use local public data", () => {
  assert.equal(resolveArtifactBaseUrl(), "/data");
  assert.equal(resolveArtifactBaseUrl({ staticDataBasePath: "/offline/data/" }), "/offline/data");
});

test("runtime artifact reads observe updated remote data without a new frontend build", async () => {
  let catalog = { sessions: [{ session_id: "2026-01-r" }] };
  const requests = [];
  const fetcher = async (_input, init) => {
    requests.push(init || {});
    return Response.json(catalog);
  };

  const first = await fetchArtifactResponse("https://worker.example/data", "catalog.json", undefined, fetcher);
  catalog = { sessions: [{ session_id: "2026-02-r" }] };
  const second = await fetchArtifactResponse("https://worker.example/data", "catalog.json", undefined, fetcher);

  assert.deepEqual(await first.json(), { sessions: [{ session_id: "2026-01-r" }] });
  assert.deepEqual(await second.json(), { sessions: [{ session_id: "2026-02-r" }] });
  assert.deepEqual(requests.map((request) => request.cache), ["no-store", "no-store"]);
});

test("one runtime artifact API exposes refreshed views and a newly published session", async () => {
  const artifacts = new Map([
    ["catalog.json", { seasons: [{ year: 2026, meeting_count: 1 }], meetings: [], sessions: [{ session_id: "2026-01-r", year: 2026, round: 1, type: "R", status: "available" }] }],
    ["seasons/2026.json", { meetings: [{ round: 1 }], sessions: [{ session_id: "2026-01-r", year: 2026, round: 1, type: "R" }] }],
    ["sessions/2026-01-r/summary.json", { meeting: "Original" }],
    ["sessions/2026-01-r/results.json", [{ driver_code: "AAA", points: 10 }]]
  ]);
  const runtimeApi = createStaticApi(async (path) => artifacts.get(path));

  artifacts.set("catalog.json", {
    seasons: [{ year: 2026, meeting_count: 2 }],
    meetings: [],
    sessions: [
      { session_id: "2026-01-r", year: 2026, round: 1, type: "R", status: "available" },
      { session_id: "2026-02-r", year: 2026, round: 2, type: "R", status: "available" }
    ]
  });
  artifacts.set("seasons/2026.json", {
    meetings: [{ round: 1 }, { round: 2 }],
    sessions: [
      { session_id: "2026-01-r", year: 2026, round: 1, type: "R" },
      { session_id: "2026-02-r", year: 2026, round: 2, type: "R" }
    ]
  });
  artifacts.set("sessions/2026-01-r/summary.json", { meeting: "Refreshed" });
  artifacts.set("sessions/2026-01-r/results.json", [{ driver_code: "AAA", points: 25 }]);

  assert.equal((await runtimeApi.seasons())[0].meeting_count, 2);
  assert.equal((await runtimeApi.meetings(2026)).length, 2);
  assert.equal((await runtimeApi.sessions(2026, 2))[0].session_id, "2026-02-r");
  assert.equal((await runtimeApi.summary("2026-01-r")).meeting, "Refreshed");
  assert.equal((await runtimeApi.results("2026-01-r"))[0].points, 25);
  assert.equal((await runtimeApi.primarySession()).session_id, "2026-02-r");
});
