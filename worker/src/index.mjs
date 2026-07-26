import { createArtifactStore } from "./artifact-store.mjs";
import { createRepository } from "./repository.mjs";
import { enqueueIngestionJob, resolveSessionStatus } from "./session-status.mjs";
import {
  artifactBasePath,
  normalizeSessionCode,
  sanitizeArtifactPath,
  sessionIdFromParts,
  sessionManifestPath
} from "./session-utils.mjs";

const LIVE_TTL_SECONDS = 3;
const MAX_JSON_BODY_BYTES = 256 * 1024;
const MAX_UPSTREAM_JSON_BYTES = 8 * 1024 * 1024;
const MAX_COMPACT_ARTIFACT_RECORDS = 100;
const MAX_QUEUE_ATTEMPTS = 3;
const DEFAULT_STALE_JOB_MINUTES = 120;
const DISABLED_LIVE_RESPONSE = {
  enabled: false,
  reason: "Live mode is disabled for this deployment.",
  setup: [
    "Set ENABLE_LIVE_MODE=true on the Cloudflare Worker.",
    "Set OPENF1_BASE_URL as a Worker variable and OPENF1_API_KEY as a secret if needed.",
    "Keep browser traffic pointed at this Worker instead of OpenF1 directly."
  ]
};

class HttpError extends Error {
  constructor(status, code, message, details = undefined) {
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

class PermanentQueueError extends Error {
  constructor(message) {
    super(message);
    this.name = "PermanentQueueError";
  }
}

export default {
  async fetch(request, env, ctx) {
    const requestId = globalThis.crypto?.randomUUID?.() || "unavailable";
    try {
      if (request.method === "OPTIONS") {
        return withCors(preflightResponse(request, env), env, request, requestId);
      }
      const response = await route(request, env, ctx, requestId);
      return withCors(response, env, request, requestId);
    } catch (error) {
      const httpError = error instanceof HttpError ? error : null;
      console.error(
        JSON.stringify({
          message: "worker request failed",
          request_id: requestId,
          method: request.method,
          path: safePathname(request.url),
          error: error instanceof Error ? error.message : String(error),
          error_name: error instanceof Error ? error.name : typeof error
        })
      );
      const payload = {
        code: httpError?.code || "worker_error",
        message: httpError?.message || "Unexpected Worker error"
      };
      if (httpError?.details !== undefined) {
        payload.details = httpError.details;
      }
      return withCors(json(payload, httpError?.status || 500), env, request, requestId);
    }
  },

  async queue(batch, env) {
    const repository = createRepository(env);
    for (const message of batch.messages) {
      try {
        await dispatchQueueMessage(message.body, env, repository);
        message.ack();
      } catch (error) {
        const permanent = error instanceof PermanentQueueError;
        console.error(
          JSON.stringify({
            message: "ingestion queue dispatch failed",
            queue_message_id: message.id,
            attempts: message.attempts,
            permanent,
            error: error instanceof Error ? error.message : String(error)
          })
        );
        if (permanent) {
          message.ack();
        } else if (Number(message.attempts) >= MAX_QUEUE_ATTEMPTS) {
          await failQueueJob(
            message.body,
            repository,
            `Queue dispatch failed after ${MAX_QUEUE_ATTEMPTS} attempts: ${
              error instanceof Error ? error.message : String(error)
            }`
          );
          message.ack();
        } else {
          message.retry({ delaySeconds: queueRetryDelay(message.attempts) });
        }
      }
    }
  },

  async scheduled(controller, env) {
    await reconcileStaleIngestionJobs(env, new Date(controller.scheduledTime));
  }
};

async function route(request, env, ctx, requestId) {
  const url = new URL(request.url);

  if (request.method === "GET" && url.pathname === "/health") {
    return json({ status: "ok", service: "formula-1-data-worker" });
  }

  if (["GET", "HEAD"].includes(request.method) && url.pathname.startsWith("/data/")) {
    return getArtifact(request, env);
  }

  if (request.method === "GET" && url.pathname === "/api/session-status") {
    return getSessionStatus(url, env);
  }

  if (request.method === "POST" && url.pathname === "/api/ingestion/session") {
    return postIngestionSession(request, env, requestId);
  }

  const jobStatusMatch = url.pathname.match(/^\/api\/ingestion\/jobs\/([^/]+)\/status$/);
  if (request.method === "POST" && jobStatusMatch) {
    return updateIngestionJob(request, env, decodePathSegment(jobStatusMatch[1], "job id"), requestId);
  }

  const jobMatch = url.pathname.match(/^\/api\/ingestion\/jobs\/([^/]+)$/);
  if (request.method === "GET" && jobMatch) {
    return getIngestionJob(env, decodePathSegment(jobMatch[1], "job id"));
  }

  if (request.method === "GET" && url.pathname.startsWith("/api/live/")) {
    return getLiveData(request, env, ctx, url.pathname.replace("/api/live/", ""));
  }

  return json({ code: "not_found", message: "Route not found" }, 404);
}

async function getArtifact(request, env) {
  const url = new URL(request.url);
  let artifactPath;
  try {
    artifactPath = sanitizeArtifactPath(url.pathname);
  } catch (error) {
    throw new HttpError(400, "invalid_artifact_path", error instanceof Error ? error.message : "Invalid path");
  }
  if (!isPublicArtifactPath(artifactPath)) {
    return json({ code: "artifact_not_found", message: "Artifact was not found" }, 404);
  }
  const artifact = await createArtifactStore(env).get(artifactPath, request);
  if (!artifact) {
    return json(
      {
        code: "artifact_not_found",
        message: "Artifact was not found",
        details: { path: artifactPath }
      },
      404
    );
  }
  return artifact;
}

export async function reconcileStaleIngestionJobs(env, now = new Date()) {
  const configured = Number(env.STALE_JOB_TIMEOUT_MINUTES || DEFAULT_STALE_JOB_MINUTES);
  const timeoutMinutes = Number.isFinite(configured) && configured > 0
    ? configured
    : DEFAULT_STALE_JOB_MINUTES;
  const cutoff = new Date(now.getTime() - timeoutMinutes * 60 * 1000).toISOString();
  return createRepository(env).failStaleJobs(
    cutoff,
    `Ingestion did not complete within ${timeoutMinutes} minutes`
  );
}

function isPublicArtifactPath(path) {
  return path === "catalog.json" || path.startsWith("seasons/") || path.startsWith("sessions/");
}

async function getSessionStatus(url, env) {
  const { year, round, session } = validateSessionLookup(
    requiredSearchParam(url, "year"),
    requiredSearchParam(url, "round"),
    requiredSearchParam(url, "session")
  );
  const status = await resolveSessionStatus({
    repository: createRepository(env),
    artifacts: createArtifactStore(env),
    year,
    round,
    session
  });
  return json(status);
}

async function postIngestionSession(request, env, requestId) {
  if (!(await isAuthorizedIngestionRequest(request, env))) {
    return json({ code: "unauthorized", message: "Ingestion request is not authorized" }, 401);
  }
  const payload = await readJsonBody(request);
  const searchParams = new URL(request.url).searchParams;
  const year = payload.year ?? searchParams.get("year");
  const round = payload.round ?? searchParams.get("round");
  const session = payload.session ?? searchParams.get("session");
  if (!year || !round || !session) {
    return json(
      {
        code: "bad_request",
        message: "year, round, and session are required"
      },
      400
    );
  }
  const lookup = validateSessionLookup(year, round, session);

  const result = await enqueueIngestionJob({
    repository: createRepository(env),
    artifacts: createArtifactStore(env),
    queue: createQueue(env),
    ...lookup,
    meetingId: optionalString(payload.meeting_id, "meeting_id", 200),
    meetingName: optionalString(payload.meeting_name, "meeting_name", 300),
    scheduledStart: optionalIsoDate(payload.scheduled_start, "scheduled_start"),
    force: optionalBoolean(payload.force, "force"),
    requestId
  });

  const status = result.action === "ready" ? 200 : result.action === "reused" ? 200 : 202;
  return json(result, status);
}

async function getIngestionJob(env, jobId) {
  validateJobId(jobId);
  const job = await createRepository(env).getJob(jobId);
  if (!job) {
    return json({ code: "job_not_found", message: "Ingestion job was not found" }, 404);
  }
  return json(job);
}

async function updateIngestionJob(request, env, jobId, requestId) {
  validateJobId(jobId);
  if (!(await isAuthorizedIngestionCallback(request, env))) {
    return json({ code: "unauthorized", message: "Ingestion callback is not authorized" }, 401);
  }

  const payload = await readJsonBody(request);
  return applyIngestionJobUpdate({
    repository: createRepository(env),
    artifacts: createArtifactStore(env),
    jobId,
    payload,
    requestId
  });
}

export async function applyIngestionJobUpdate({ repository, artifacts, jobId, payload, requestId = null }) {
  const status = String(payload.status || "").toLowerCase();
  if (!["running", "succeeded", "failed"].includes(status)) {
    return json({ code: "bad_request", message: "status must be running, succeeded, or failed" }, 400);
  }
  const errorMessage = optionalString(payload.error_message, "error_message", 2000);
  const generatedAt = optionalIsoDate(payload.generated_at, "generated_at");
  let artifactRecords = null;
  if (payload.artifacts !== undefined) {
    if (!Array.isArray(payload.artifacts)) {
      throw new HttpError(400, "bad_request", "artifacts must be an array");
    }
    artifactRecords = validateArtifactRecords(payload.artifacts);
  }
  const manifest = status === "succeeded" ? validateManifestRecord(payload.manifest) : null;
  const quality = validateQuality(payload.quality);

  const existing = await repository.getJob(jobId);
  if (!existing) {
    return json({ code: "job_not_found", message: "Ingestion job was not found" }, 404);
  }
  if (["succeeded", "failed"].includes(existing.status)) {
    const terminalStatus = existing.status === "succeeded" ? "ready" : "failed";
    return json({ job: existing, status: terminalStatus });
  }
  if (manifest) {
    validateManifestOwnership(manifest, existing.session_id);
  }
  if (artifactRecords) {
    validateArtifactOwnership(artifactRecords, existing.session_id);
  }

  if (status === "succeeded") {
    let verification;
    try {
      verification = await artifacts.verify(manifest, { r2Only: true });
    } catch (error) {
      verification = {
        verified: false,
        reason: "verification_error",
        error: error instanceof Error ? error.message : String(error)
      };
    }
    logLifecycle({
      requestId,
      jobId,
      sessionId: existing.session_id,
      transition: "running->publication_verification",
      artifactVerification: verification.verified ? "succeeded" : verification.reason || "failed"
    });
    if (!verification.verified) {
      const message = `Manifest publication verification failed: ${verification.reason || "unknown error"}`;
      await failIngestionTransition(repository, existing, message);
      logLifecycle({
        requestId,
        jobId,
        sessionId: existing.session_id,
        transition: `${existing.status}->failed`,
        artifactVerification: verification.reason || "failed"
      });
      throw new HttpError(409, "publication_verification_failed", message, verification);
    }
  }

  const now = new Date().toISOString();
  if (status === "succeeded") {
    await repository.recordArtifacts(existing.session_id, [manifest, ...(artifactRecords || [])]);
  }

  const sessionStatus = status === "succeeded" ? "ready" : status === "running" ? "ingesting" : "failed";
  const session = await repository.getSession(existing.session_id);
  const transition = await repository.transitionJobAndSession(jobId, {
    status,
    error_message: errorMessage,
    started_at: status === "running" ? existing.started_at || now : existing.started_at,
    finished_at: status === "succeeded" || status === "failed" ? now : existing.finished_at
  }, {
    session_id: existing.session_id,
    status: sessionStatus,
    generated_at: generatedAt || (status === "succeeded" ? now : session?.generated_at),
    quality_json: quality ? JSON.stringify(quality) : session?.quality_json || null
  });
  if (!transition) {
    throw new Error("Failed to transition the ingestion job and session together");
  }
  const job = transition.job;

  logLifecycle({
    requestId,
    jobId,
    sessionId: existing.session_id,
    transition: `${existing.status}->${status}`,
    artifactVerification: status === "succeeded" ? "succeeded" : "not_applicable"
  });

  return json({ job, status: sessionStatus });
}

async function getLiveData(request, env, ctx, livePath) {
  if (String(env.ENABLE_LIVE_MODE || "false").toLowerCase() !== "true") {
    return json(DISABLED_LIVE_RESPONSE);
  }

  const cache = caches.default;
  const cacheKey = new Request(request.url, request);
  const cached = await cache.match(cacheKey);
  if (cached) {
    return cached;
  }

  let payload;
  if (livePath === "current-session") {
    payload = await openF1Get(env, "sessions", { session_key: "latest" });
  } else if (livePath === "timing") {
    const [drivers, intervals, laps] = await Promise.all([
      openF1Get(env, "drivers", { session_key: "latest" }),
      openF1Get(env, "intervals", { session_key: "latest" }),
      openF1Get(env, "laps", { session_key: "latest" })
    ]);
    payload = {
      drivers,
      intervals,
      laps
    };
  } else if (livePath === "race-control") {
    payload = await openF1Get(env, "race_control", { session_key: "latest" });
  } else if (livePath === "positions") {
    payload = await openF1Get(env, "position", { session_key: "latest" });
  } else if (livePath === "weather") {
    payload = await openF1Get(env, "weather", { session_key: "latest" });
  } else {
    return json({ code: "not_found", message: "Live route not found" }, 404);
  }

  const response = json(payload, 200, {
    "cache-control": `public, max-age=${LIVE_TTL_SECONDS}`
  });
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  ctx.waitUntil(
    createRepository(env).storeLiveSnapshot(livePath, payload, new Date().toISOString()).catch((error) => {
      console.error(
        JSON.stringify({
          message: "failed to store live snapshot",
          live_path: livePath,
          error: error instanceof Error ? error.message : String(error)
        })
      );
    })
  );
  return response;
}

async function openF1Get(env, endpoint, params) {
  const baseUrl = validatedExternalUrl(env.OPENF1_BASE_URL || "https://api.openf1.org/v1", "OPENF1_BASE_URL");
  const url = new URL(`${baseUrl.replace(/\/$/, "")}/${endpoint.replace(/^\//, "")}`);
  for (const [key, value] of Object.entries(params || {})) {
    url.searchParams.set(key, value);
  }
  const headers = new Headers();
  if (env.OPENF1_API_KEY) {
    headers.set("x-api-key", env.OPENF1_API_KEY);
  }
  const response = await fetch(url, { headers });
  if (!response.ok) {
    return {
      enabled: false,
      reason: `OpenF1 ${endpoint} returned ${response.status}.`,
      setup: ["Live data will retry on the next poll."]
    };
  }
  return {
    endpoint,
    data: await readBoundedJsonResponse(response, MAX_UPSTREAM_JSON_BYTES, `OpenF1 ${endpoint}`),
    cached: false
  };
}

export async function dispatchQueueMessage(body, env, repository) {
  validateQueueMessage(body);
  const jobId = body.job_id;

  const now = new Date().toISOString();
  const current = await repository.getJob(jobId);
  if (!current) {
    throw new PermanentQueueError(`Queue message references unknown job ${jobId}`);
  }
  if (current.session_id !== body.session_id || current.kind !== body.kind) {
    throw new PermanentQueueError("Queue message does not match the stored ingestion job");
  }
  if (["succeeded", "failed"].includes(current.status)) {
    return;
  }
  await repository.updateJob(jobId, {
    status: "running",
    attempts: Number(current?.attempts || 0) + 1,
    started_at: current?.started_at || now,
    error_message: null
  });
  logLifecycle({
    requestId: null,
    jobId,
    sessionId: body.session_id,
    transition: `${current.status}->running`,
    artifactVerification: "not_applicable"
  });

  if (hasGitHubDispatchConfig(env)) {
    await dispatchGitHubWorkflow(body, env, repository);
    return;
  }

  if (!env.INGESTION_WEBHOOK_URL) {
    await failQueueDispatchWithoutRunner(body, repository);
    return;
  }

  let webhookUrl;
  try {
    webhookUrl = validatedExternalUrl(env.INGESTION_WEBHOOK_URL, "INGESTION_WEBHOOK_URL");
  } catch (error) {
    await failQueueJob(body, repository, error instanceof Error ? error.message : "Invalid ingestion webhook URL");
    return;
  }

  const headers = new Headers({ "content-type": "application/json" });
  if (env.INGESTION_WEBHOOK_TOKEN) {
    headers.set("authorization", `Bearer ${env.INGESTION_WEBHOOK_TOKEN}`);
  }

  const response = await fetch(webhookUrl, {
    method: "POST",
    headers,
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const errorMessage = `Ingestion webhook returned ${response.status}`;
    if (!isRetryableUpstreamStatus(response.status)) {
      await failQueueJob(body, repository, errorMessage);
      return;
    }
    await repository.updateJob(jobId, {
      status: "queued",
      error_message: errorMessage
    });
    throw new Error(errorMessage);
  }
}

function hasGitHubDispatchConfig(env) {
  return Boolean(env.GITHUB_DISPATCH_TOKEN && env.GITHUB_REPO_OWNER && env.GITHUB_REPO_NAME);
}

async function dispatchGitHubWorkflow(body, env, repository) {
  const owner = String(env.GITHUB_REPO_OWNER).trim();
  const repo = String(env.GITHUB_REPO_NAME).trim();
  const eventType = String(env.GITHUB_DISPATCH_EVENT || "ingest_session").trim();
  const url = `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/dispatches`;

  // dispatchQueueMessage already moved the job to `running` with a `started_at`.
  // Whenever the dispatch is not confirmed, that has to be undone: a `running`
  // job with a `started_at` is indistinguishable from a workflow that started
  // and hung, so the only thing that ever clears it is the stale-job
  // reconciler, two hours later, reporting a timeout that never happened.
  // Reverting to `queued` with no `started_at` keeps "never started" and
  // "started and hung" as different states in D1.
  const revertToQueued = async (errorMessage) => {
    await repository.updateJob(body.job_id, {
      status: "queued",
      started_at: null,
      error_message: errorMessage
    });
  };

  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: {
        accept: "application/vnd.github+json",
        authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
        "content-type": "application/json",
        "user-agent": "formula-1-data-worker",
        "x-github-api-version": "2022-11-28"
      },
      body: JSON.stringify({
        event_type: eventType,
        client_payload: {
          message: body
        }
      })
    });
  } catch (error) {
    // The request never produced a response, so no workflow run can exist.
    const errorMessage = `GitHub repository_dispatch request failed: ${
      error instanceof Error ? error.message : String(error)
    }`;
    await revertToQueued(errorMessage);
    throw new Error(errorMessage);
  }

  if (!response.ok) {
    const errorMessage = `GitHub repository_dispatch returned ${response.status}`;
    if (!isRetryableUpstreamStatus(response.status)) {
      await failQueueJob(body, repository, errorMessage);
      return;
    }
    await revertToQueued(errorMessage);
    throw new Error(errorMessage);
  }
}

async function failQueueDispatchWithoutRunner(body, repository) {
  const errorMessage =
    "No GitHub dispatch configuration or INGESTION_WEBHOOK_URL is configured, so the Worker cannot dispatch this job to an external Python ingestion runner.";
  await failQueueJob(body, repository, errorMessage);
}

async function failQueueJob(body, repository, errorMessage) {
  const jobId = body.job_id;
  const current = await repository.getJob(jobId);
  const now = new Date().toISOString();
  const sessionId = current?.session_id || body.session_id;
  if (!sessionId) {
    return;
  }
  const transition = await repository.transitionJobAndSession(jobId, {
    status: "failed",
    attempts: Number(current?.attempts || 0),
    error_message: errorMessage,
    started_at: current?.started_at || null,
    finished_at: now
  }, {
    session_id: sessionId,
    status: "failed"
  });
  if (!transition) {
    throw new Error("Failed to transition the queue job and session to failed");
  }
  logLifecycle({
    requestId: null,
    jobId,
    sessionId,
    transition: `${current?.status || "unknown"}->failed`,
    artifactVerification: "not_applicable"
  });
}

async function failIngestionTransition(repository, existingJob, errorMessage) {
  const now = new Date().toISOString();
  const transition = await repository.transitionJobAndSession(existingJob.job_id, {
    status: "failed",
    error_message: errorMessage,
    started_at: existingJob.started_at || null,
    finished_at: now
  }, {
    session_id: existingJob.session_id,
    status: "failed"
  });
  if (!transition) {
    throw new Error("Failed to record the publication verification failure");
  }
}

function logLifecycle({ requestId, jobId, sessionId, transition, artifactVerification }) {
  console.info(
    JSON.stringify({
      message: "ingestion lifecycle transition",
      request_id: requestId,
      job_id: jobId,
      session_id: sessionId,
      lifecycle_transition: transition,
      artifact_verification_result: artifactVerification,
      queue_send_result: "not_applicable"
    })
  );
}

function createQueue(env) {
  if (!env.INGESTION_QUEUE?.send) {
    throw new Error("Required INGESTION_QUEUE binding is unavailable");
  }
  return env.INGESTION_QUEUE;
}

function requiredSearchParam(url, name) {
  const value = url.searchParams.get(name);
  if (!value) {
    throw new HttpError(400, "bad_request", `${name} is required`);
  }
  return value;
}

async function readJsonBody(request) {
  if (!request.body) {
    return {};
  }
  const contentType = request.headers.get("content-type") || "";
  if (!/(^|\s|;)application\/(?:[a-z0-9.+-]*\+)?json(?:\s*;|$)/i.test(contentType)) {
    throw new HttpError(415, "unsupported_media_type", "Request body must use application/json");
  }
  return readBoundedJsonStream(
    request.body,
    request.headers.get("content-length"),
    MAX_JSON_BODY_BYTES,
    "Request body",
    true
  );
}

export async function isAuthorizedIngestionCallback(request, env) {
  if (env.ALLOW_UNAUTHENTICATED_INGESTION_CALLBACKS === "true") {
    return true;
  }
  if (!env.INGESTION_API_TOKEN) {
    return false;
  }
  const provided = bearerToken(request);
  return provided ? timingSafeSecretEqual(provided, String(env.INGESTION_API_TOKEN)) : false;
}

export async function isAuthorizedIngestionRequest(request, env) {
  if (env.REQUIRE_INGESTION_REQUEST_AUTH !== "true") {
    return true;
  }
  if (!env.INGESTION_API_TOKEN) {
    return false;
  }
  const provided = bearerToken(request);
  return provided ? timingSafeSecretEqual(provided, String(env.INGESTION_API_TOKEN)) : false;
}

export async function timingSafeSecretEqual(provided, expected) {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    globalThis.crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    globalThis.crypto.subtle.digest("SHA-256", encoder.encode(expected))
  ]);
  if (typeof globalThis.crypto.subtle.timingSafeEqual === "function") {
    return globalThis.crypto.subtle.timingSafeEqual(providedHash, expectedHash);
  }

  // Node's Web Crypto does not yet expose timingSafeEqual. Keep unit tests and
  // local development constant-time without requiring nodejs_compat in Workers.
  const left = new Uint8Array(providedHash);
  const right = new Uint8Array(expectedHash);
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left[index] ^ right[index];
  }
  return difference === 0;
}

function json(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...headers
    }
  });
}

function withCors(response, env, request, requestId) {
  const headers = new Headers(response.headers);
  const allowedOrigin = corsOrigin(request, env);
  if (allowedOrigin) {
    headers.set("access-control-allow-origin", allowedOrigin);
  } else {
    headers.delete("access-control-allow-origin");
  }
  headers.set("access-control-allow-methods", "GET,HEAD,POST,OPTIONS");
  headers.set("access-control-allow-headers", "content-type,authorization");
  headers.set("access-control-expose-headers", "etag,last-modified,content-length,content-range,x-request-id");
  headers.set("access-control-max-age", "86400");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "no-referrer");
  headers.set("x-request-id", requestId);
  if (allowedOrigin && allowedOrigin !== "*") {
    appendVary(headers, "Origin");
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

function preflightResponse(request, env) {
  const requestedMethod = request.headers.get("access-control-request-method");
  if (requestedMethod && !["GET", "POST", "HEAD"].includes(requestedMethod.toUpperCase())) {
    return json({ code: "method_not_allowed", message: "CORS method is not allowed" }, 405);
  }
  if (request.headers.get("origin") && !corsOrigin(request, env)) {
    return json({ code: "cors_origin_denied", message: "CORS origin is not allowed" }, 403);
  }
  return new Response(null, { status: 204 });
}

function corsOrigin(request, env) {
  const configured = String(env.CORS_ALLOW_ORIGIN || "*")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (configured.includes("*")) {
    return "*";
  }
  const origin = request.headers.get("origin");
  return origin && configured.includes(origin) ? origin : null;
}

function appendVary(headers, value) {
  const values = new Set(
    String(headers.get("vary") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
  );
  values.add(value);
  headers.set("vary", Array.from(values).join(", "));
}

function bearerToken(request) {
  const match = String(request.headers.get("authorization") || "").match(/^Bearer ([^\s]+)$/i);
  return match?.[1] || null;
}

function validateSessionLookup(year, round, session) {
  try {
    const normalizedSession = normalizeSessionCode(session);
    sessionIdFromParts(year, round, normalizedSession);
    return {
      year: Number(year),
      round: Number(round),
      session: normalizedSession
    };
  } catch (error) {
    throw new HttpError(400, "bad_request", error instanceof Error ? error.message : "Invalid session lookup");
  }
}

function validateJobId(jobId) {
  if (!jobId || jobId.length > 300 || !/^[A-Za-z0-9:_-]+$/.test(jobId)) {
    throw new HttpError(400, "bad_request", "job id is invalid");
  }
}

function decodePathSegment(value, label) {
  try {
    return decodeURIComponent(value);
  } catch {
    throw new HttpError(400, "bad_request", `${label} contains invalid encoding`);
  }
}

function optionalString(value, name, maximumLength) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  if (typeof value !== "string") {
    throw new HttpError(400, "bad_request", `${name} must be a string`);
  }
  const normalized = value.trim();
  if (!normalized || normalized.length > maximumLength) {
    throw new HttpError(400, "bad_request", `${name} must contain 1 to ${maximumLength} characters`);
  }
  return normalized;
}

function optionalBoolean(value, name) {
  if (value === undefined || value === null || value === "") {
    return false;
  }
  if (value === true || value === "true") {
    return true;
  }
  if (value === false || value === "false") {
    return false;
  }
  throw new HttpError(400, "bad_request", `${name} must be a boolean`);
}

function optionalIsoDate(value, name) {
  const normalized = optionalString(value, name, 64);
  if (normalized === null) {
    return null;
  }
  if (!Number.isFinite(Date.parse(normalized))) {
    throw new HttpError(400, "bad_request", `${name} must be an ISO-8601 date-time`);
  }
  return normalized;
}

function validateArtifactRecords(artifacts) {
  if (artifacts.length > MAX_COMPACT_ARTIFACT_RECORDS) {
    throw new HttpError(
      400,
      "bad_request",
      `artifacts must be a compact manifest summary with no more than ${MAX_COMPACT_ARTIFACT_RECORDS} records`
    );
  }
  return artifacts.map((artifact, index) => validateArtifactRecord(artifact, `artifacts[${index}]`));
}

function validateManifestRecord(manifest) {
  if (manifest === undefined || manifest === null) {
    throw new HttpError(400, "bad_request", "succeeded callbacks require a manifest record");
  }
  const record = validateArtifactRecord(manifest, "manifest");
  if (record.kind !== "manifest") {
    throw new HttpError(400, "bad_request", "manifest.kind must be manifest");
  }
  return record;
}

function validateArtifactRecord(artifact, label) {
    if (!artifact || typeof artifact !== "object" || Array.isArray(artifact)) {
      throw new HttpError(400, "bad_request", `${label} must be an object`);
    }
    const kind = optionalString(artifact.kind, `${label}.kind`, 64);
    const rawPath = optionalString(artifact.path, `${label}.path`, 1024);
    if (!kind || !rawPath || !/^[A-Za-z0-9._:-]+$/.test(kind)) {
      throw new HttpError(400, "bad_request", `${label} has an invalid kind or path`);
    }
    let path;
    try {
      path = sanitizeArtifactPath(rawPath);
    } catch (error) {
      throw new HttpError(
        400,
        "bad_request",
        `${label}.path is invalid: ${error instanceof Error ? error.message : "invalid path"}`
      );
    }
    const sizeBytes = artifact.size_bytes;
    if (!Number.isSafeInteger(sizeBytes) || sizeBytes < 0) {
      throw new HttpError(400, "bad_request", `${label}.size_bytes must be a non-negative integer`);
    }
    const checksum = optionalString(artifact.checksum, `${label}.checksum`, 71);
    if (!checksum || !/^sha256:[a-f0-9]{64}$/.test(checksum)) {
      throw new HttpError(400, "bad_request", `${label}.checksum must be a lowercase sha256 checksum`);
    }
    const metadata = validateArtifactMetadata(artifact.metadata, `${label}.metadata`);
    return {
      kind,
      path,
      size_bytes: sizeBytes,
      checksum,
      generated_at: optionalIsoDate(artifact.generated_at, `${label}.generated_at`),
      metadata
    };
}

function validateArtifactOwnership(artifacts, sessionId) {
  const expectedPrefix = `${artifactBasePath(sessionId)}/`;
  for (const artifact of artifacts) {
    if (!artifact.path.startsWith(expectedPrefix)) {
      throw new HttpError(400, "bad_request", "artifact paths must belong to the ingestion job session");
    }
  }
}

function validateManifestOwnership(manifest, sessionId) {
  if (manifest.path !== sessionManifestPath(sessionId)) {
    throw new HttpError(400, "bad_request", "manifest path must belong to the ingestion job session");
  }
}

function validateArtifactMetadata(value, name) {
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "object" || Array.isArray(value)) {
    throw new HttpError(400, "bad_request", `${name} must be an object`);
  }
  if (JSON.stringify(value).length > 16_384) {
    throw new HttpError(400, "bad_request", `${name} is too large`);
  }
  return value;
}

function validateQuality(value) {
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "object" || Array.isArray(value)) {
    throw new HttpError(400, "bad_request", "quality must be an object");
  }
  const status = optionalString(value.status, "quality.status", 32);
  if (!status || !["complete", "partial", "unknown"].includes(status)) {
    throw new HttpError(400, "bad_request", "quality.status must be complete, partial, or unknown");
  }
  return {
    status,
    missing_sections: validateStringList(value.missing_sections, "quality.missing_sections"),
    available_sections: validateStringList(value.available_sections, "quality.available_sections")
  };
}

function validateStringList(value, name) {
  if (value === undefined || value === null) {
    return [];
  }
  if (!Array.isArray(value) || value.length > 100) {
    throw new HttpError(400, "bad_request", `${name} must be an array with no more than 100 values`);
  }
  return value.map((item, index) => {
    const normalized = optionalString(item, `${name}[${index}]`, 100);
    if (!normalized) {
      throw new HttpError(400, "bad_request", `${name}[${index}] is invalid`);
    }
    return normalized;
  });
}

function validateQueueMessage(body) {
  try {
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      throw new Error("Queue message must be an object");
    }
    if (body.version !== 1 || body.kind !== "ingest_session") {
      throw new Error("Queue message has an unsupported version or kind");
    }
    validateJobId(body.job_id);
    const lookup = validateSessionLookup(body.year, body.round, body.session);
    const expectedSessionId = sessionIdFromParts(lookup.year, lookup.round, lookup.session);
    if (body.session_id !== expectedSessionId) {
      throw new Error("Queue message session_id does not match its session fields");
    }
    if (body.artifact_base_path !== artifactBasePath(expectedSessionId)) {
      throw new Error("Queue message artifact_base_path does not match its session");
    }
  } catch (error) {
    throw new PermanentQueueError(error instanceof Error ? error.message : "Invalid queue message");
  }
}

async function readBoundedJsonResponse(response, maximumBytes, label) {
  if (!response.body) {
    throw new Error(`${label} returned an empty response`);
  }
  return readBoundedJsonStream(response.body, response.headers.get("content-length"), maximumBytes, label, false);
}

async function readBoundedJsonStream(stream, contentLength, maximumBytes, label, requireObject) {
  const declaredLength = Number.parseInt(String(contentLength || ""), 10);
  if (Number.isFinite(declaredLength) && declaredLength > maximumBytes) {
    throw new HttpError(413, "payload_too_large", `${label} exceeds the ${maximumBytes}-byte limit`);
  }

  const reader = stream.getReader();
  const chunks = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      totalBytes += value.byteLength;
      if (totalBytes > maximumBytes) {
        await reader.cancel();
        throw new HttpError(413, "payload_too_large", `${label} exceeds the ${maximumBytes}-byte limit`);
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }

  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new HttpError(400, "invalid_json", `${label} contains invalid JSON`);
  }
  if (requireObject && (!payload || typeof payload !== "object" || Array.isArray(payload))) {
    throw new HttpError(400, "invalid_json", `${label} must contain a JSON object`);
  }
  return payload;
}

function queueRetryDelay(attempts) {
  const safeAttempts = Math.max(1, Math.min(Number(attempts) || 1, 6));
  return Math.min(30 * 2 ** (safeAttempts - 1), 900);
}

function safePathname(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return "<invalid-url>";
  }
}

function validatedExternalUrl(value, name) {
  let url;
  try {
    url = new URL(String(value));
  } catch {
    throw new Error(`${name} must be a valid URL`);
  }
  const isLocal = url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]";
  if (url.protocol !== "https:" && !(url.protocol === "http:" && isLocal)) {
    throw new Error(`${name} must use HTTPS`);
  }
  if (url.username || url.password) {
    throw new Error(`${name} cannot contain embedded credentials`);
  }
  return url.toString();
}

function isRetryableUpstreamStatus(status) {
  return status === 408 || status === 429 || status >= 500;
}
