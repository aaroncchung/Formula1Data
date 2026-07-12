import assert from "node:assert/strict";
import test from "node:test";

import worker, {
  isAuthorizedIngestionCallback,
  isAuthorizedIngestionRequest
} from "../src/index.mjs";

const context = { waitUntil() {} };

test("ingestion callback authorization accepts only the configured bearer token", async () => {
  const env = { INGESTION_API_TOKEN: "correct-horse-battery-staple" };
  const valid = new Request("https://worker.example/api/ingestion/jobs/job/status", {
    headers: { authorization: "Bearer correct-horse-battery-staple" }
  });
  const invalid = new Request("https://worker.example/api/ingestion/jobs/job/status", {
    headers: { authorization: "Bearer incorrect-token" }
  });
  const missing = new Request("https://worker.example/api/ingestion/jobs/job/status");

  assert.equal(await isAuthorizedIngestionCallback(valid, env), true);
  assert.equal(await isAuthorizedIngestionCallback(invalid, env), false);
  assert.equal(await isAuthorizedIngestionCallback(missing, env), false);
});

test("browser ingestion requests remain compatible unless token auth is explicitly required", async () => {
  const request = new Request("https://worker.example/api/ingestion/session", { method: "POST" });

  assert.equal(await isAuthorizedIngestionRequest(request, {}), true);
  assert.equal(
    await isAuthorizedIngestionRequest(request, {
      REQUIRE_INGESTION_REQUEST_AUTH: "true",
      INGESTION_API_TOKEN: "secret"
    }),
    false
  );
});

test("missing session-status parameters return a structured 400", async () => {
  const response = await worker.fetch(
    new Request("https://worker.example/api/session-status?year=2026&round=4"),
    {},
    context
  );
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), {
    code: "bad_request",
    message: "session is required"
  });
});

test("invalid JSON and unsupported content types are rejected before binding access", async () => {
  const malformed = await worker.fetch(
    new Request("https://worker.example/api/ingestion/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{"
    }),
    {},
    context
  );
  assert.equal(malformed.status, 400);
  assert.equal((await malformed.json()).code, "invalid_json");

  const unsupported = await worker.fetch(
    new Request("https://worker.example/api/ingestion/session", {
      method: "POST",
      headers: { "content-type": "text/plain" },
      body: "year=2026"
    }),
    {},
    context
  );
  assert.equal(unsupported.status, 415);
  assert.equal((await unsupported.json()).code, "unsupported_media_type");
});

test("invalid artifact paths return 400 instead of leaking a Worker exception", async () => {
  const response = await worker.fetch(
    new Request("https://worker.example/data/%E0%A4%A"),
    {},
    context
  );
  assert.equal(response.status, 400);
  assert.equal((await response.json()).code, "invalid_artifact_path");
});

test("private source datasets are not exposed through the public data route", async () => {
  const response = await worker.fetch(
    new Request("https://worker.example/data/source/sessions/2026-09-r/dataset.json"),
    {},
    context
  );
  assert.equal(response.status, 404);
  assert.equal((await response.json()).code, "artifact_not_found");
});

test("explicit ingestion request auth rejects missing credentials", async () => {
  const response = await worker.fetch(
    new Request("https://worker.example/api/ingestion/session", { method: "POST" }),
    {
      REQUIRE_INGESTION_REQUEST_AUTH: "true",
      INGESTION_API_TOKEN: "secret"
    },
    context
  );
  assert.equal(response.status, 401);
  assert.equal((await response.json()).code, "unauthorized");
});

test("CORS preflight honors an explicit origin allowlist", async () => {
  const allowed = await worker.fetch(
    new Request("https://worker.example/api/session-status", {
      method: "OPTIONS",
      headers: {
        origin: "https://formula1data.pages.dev",
        "access-control-request-method": "GET"
      }
    }),
    { CORS_ALLOW_ORIGIN: "https://formula1data.pages.dev" },
    context
  );
  assert.equal(allowed.status, 204);
  assert.equal(allowed.headers.get("access-control-allow-origin"), "https://formula1data.pages.dev");
  assert.match(allowed.headers.get("vary"), /Origin/);

  const denied = await worker.fetch(
    new Request("https://worker.example/api/session-status", {
      method: "OPTIONS",
      headers: {
        origin: "https://attacker.example",
        "access-control-request-method": "GET"
      }
    }),
    { CORS_ALLOW_ORIGIN: "https://formula1data.pages.dev" },
    context
  );
  assert.equal(denied.status, 403);
  assert.equal(denied.headers.get("access-control-allow-origin"), null);
});
