import { createArtifactStore } from "./artifact-store.mjs";
import { createRepository } from "./repository.mjs";
import { enqueueIngestionJob, resolveSessionStatus } from "./session-status.mjs";
import { sanitizeArtifactPath } from "./session-utils.mjs";

const LIVE_TTL_SECONDS = 3;
const DISABLED_LIVE_RESPONSE = {
  enabled: false,
  reason: "Live mode is disabled for this deployment.",
  setup: [
    "Set ENABLE_LIVE_MODE=true on the Cloudflare Worker.",
    "Set OPENF1_BASE_URL and OPENF1_API_KEY as Worker variables or secrets if needed.",
    "Keep browser traffic pointed at this Worker instead of OpenF1 directly."
  ]
};

export default {
  async fetch(request, env, ctx) {
    try {
      if (request.method === "OPTIONS") {
        return withCors(new Response(null, { status: 204 }), env);
      }
      const response = await route(request, env, ctx);
      return withCors(response, env);
    } catch (error) {
      return withCors(
        json(
          {
            code: "worker_error",
            message: error instanceof Error ? error.message : "Unexpected Worker error"
          },
          500
        ),
        env
      );
    }
  },

  async queue(batch, env, ctx) {
    const repository = createRepository(env);
    for (const message of batch.messages) {
      try {
        await dispatchQueueMessage(message.body, env, repository);
        message.ack?.();
      } catch (error) {
        console.error("Failed to dispatch ingestion queue message", error);
        message.retry?.();
      }
    }
  }
};

async function route(request, env, ctx) {
  const url = new URL(request.url);

  if (url.pathname === "/health") {
    return json({ status: "ok", service: "formula-1-data-worker" });
  }

  if (request.method === "GET" && url.pathname.startsWith("/data/")) {
    return getArtifact(request, env);
  }

  if (request.method === "GET" && url.pathname === "/api/session-status") {
    return getSessionStatus(url, env);
  }

  if (request.method === "POST" && url.pathname === "/api/ingestion/session") {
    return postIngestionSession(request, env);
  }

  const jobStatusMatch = url.pathname.match(/^\/api\/ingestion\/jobs\/([^/]+)\/status$/);
  if (request.method === "POST" && jobStatusMatch) {
    return updateIngestionJob(request, env, decodeURIComponent(jobStatusMatch[1]));
  }

  const jobMatch = url.pathname.match(/^\/api\/ingestion\/jobs\/([^/]+)$/);
  if (request.method === "GET" && jobMatch) {
    return getIngestionJob(env, decodeURIComponent(jobMatch[1]));
  }

  if (request.method === "GET" && url.pathname.startsWith("/api/live/")) {
    return getLiveData(request, env, ctx, url.pathname.replace("/api/live/", ""));
  }

  return json({ code: "not_found", message: "Route not found" }, 404);
}

async function getArtifact(request, env) {
  const url = new URL(request.url);
  const artifactPath = sanitizeArtifactPath(url.pathname);
  const artifact = await createArtifactStore(env).get(artifactPath);
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

async function getSessionStatus(url, env) {
  const year = requiredSearchParam(url, "year");
  const round = requiredSearchParam(url, "round");
  const session = requiredSearchParam(url, "session");
  const status = await resolveSessionStatus({
    repository: createRepository(env),
    artifacts: createArtifactStore(env),
    year,
    round,
    session
  });
  return json(status);
}

async function postIngestionSession(request, env) {
  const payload = await readJsonBody(request);
  const year = payload.year ?? new URL(request.url).searchParams.get("year");
  const round = payload.round ?? new URL(request.url).searchParams.get("round");
  const session = payload.session ?? new URL(request.url).searchParams.get("session");
  if (!year || !round || !session) {
    return json(
      {
        code: "bad_request",
        message: "year, round, and session are required"
      },
      400
    );
  }

  const result = await enqueueIngestionJob({
    repository: createRepository(env),
    artifacts: createArtifactStore(env),
    queue: createQueue(env),
    year,
    round,
    session,
    meetingId: payload.meeting_id || null,
    meetingName: payload.meeting_name || null,
    scheduledStart: payload.scheduled_start || null,
    force: Boolean(payload.force)
  });

  const status = result.action === "ready" ? 200 : result.action === "reused" ? 200 : 202;
  return json(result, status);
}

async function getIngestionJob(env, jobId) {
  const job = await createRepository(env).getJob(jobId);
  if (!job) {
    return json({ code: "job_not_found", message: "Ingestion job was not found" }, 404);
  }
  return json(job);
}

async function updateIngestionJob(request, env, jobId) {
  if (!isAuthorizedIngestionCallback(request, env)) {
    return json({ code: "unauthorized", message: "Ingestion callback is not authorized" }, 401);
  }

  const payload = await readJsonBody(request);
  const status = String(payload.status || "").toLowerCase();
  if (!["running", "succeeded", "failed"].includes(status)) {
    return json({ code: "bad_request", message: "status must be running, succeeded, or failed" }, 400);
  }

  const repository = createRepository(env);
  const existing = await repository.getJob(jobId);
  if (!existing) {
    return json({ code: "job_not_found", message: "Ingestion job was not found" }, 404);
  }

  const now = new Date().toISOString();
  const job = await repository.updateJob(jobId, {
    status,
    error_message: payload.error_message || null,
    started_at: status === "running" ? existing.started_at || now : existing.started_at,
    finished_at: status === "succeeded" || status === "failed" ? now : existing.finished_at
  });

  const sessionStatus = status === "succeeded" ? "ready" : status === "running" ? "ingesting" : "failed";
  const session = await repository.getSession(existing.session_id);
  if (session) {
    await repository.upsertSession({
      ...session,
      status: sessionStatus,
      generated_at: payload.generated_at || (status === "succeeded" ? now : session.generated_at)
    });
  }

  if (status === "succeeded" && Array.isArray(payload.artifacts)) {
    await repository.recordArtifacts(existing.session_id, payload.artifacts);
  }

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
    createRepository(env).storeLiveSnapshot(livePath, payload, new Date().toISOString()).catch(() => undefined)
  );
  return response;
}

async function openF1Get(env, endpoint, params) {
  const baseUrl = env.OPENF1_BASE_URL || "https://api.openf1.org/v1";
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
    data: await response.json(),
    cached: false
  };
}

async function dispatchQueueMessage(body, env, repository) {
  const jobId = body?.job_id;
  if (!jobId) {
    throw new Error("Queue message is missing job_id");
  }

  if (!env.INGESTION_WEBHOOK_URL) {
    await repository.incrementJobAttempts(
      jobId,
      "No INGESTION_WEBHOOK_URL configured; an external Python ingestion runner must process this job."
    );
    return;
  }

  const now = new Date().toISOString();
  const current = await repository.getJob(jobId);
  await repository.updateJob(jobId, {
    status: "running",
    attempts: Number(current?.attempts || 0) + 1,
    started_at: current?.started_at || now,
    error_message: null
  });

  const headers = new Headers({ "content-type": "application/json" });
  if (env.INGESTION_WEBHOOK_TOKEN) {
    headers.set("authorization", `Bearer ${env.INGESTION_WEBHOOK_TOKEN}`);
  }

  const response = await fetch(env.INGESTION_WEBHOOK_URL, {
    method: "POST",
    headers,
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    await repository.updateJob(jobId, {
      status: "queued",
      error_message: `Ingestion webhook returned ${response.status}`
    });
    throw new Error(`Ingestion webhook returned ${response.status}`);
  }
}

function createQueue(env) {
  return {
    async send(message) {
      if (env.INGESTION_QUEUE?.send) {
        await env.INGESTION_QUEUE.send(message);
        return;
      }
      console.log("Mock ingestion queue message", JSON.stringify(message));
    }
  };
}

function requiredSearchParam(url, name) {
  const value = url.searchParams.get(name);
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

async function readJsonBody(request) {
  if (!request.headers.get("content-type")?.includes("application/json")) {
    return {};
  }
  return request.json();
}

function isAuthorizedIngestionCallback(request, env) {
  if (env.ALLOW_UNAUTHENTICATED_INGESTION_CALLBACKS === "true") {
    return true;
  }
  if (!env.INGESTION_API_TOKEN) {
    return false;
  }
  return request.headers.get("authorization") === `Bearer ${env.INGESTION_API_TOKEN}`;
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

function withCors(response, env) {
  const headers = new Headers(response.headers);
  headers.set("access-control-allow-origin", env.CORS_ALLOW_ORIGIN || "*");
  headers.set("access-control-allow-methods", "GET,POST,OPTIONS");
  headers.set("access-control-allow-headers", "content-type,authorization");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}
