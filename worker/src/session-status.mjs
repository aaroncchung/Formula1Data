import {
  artifactBasePath,
  makeJobId,
  normalizeSessionCode,
  queueMessageForJob,
  sessionIdFromParts,
  sessionManifestPath
} from "./session-utils.mjs";

export const INGEST_SESSION = "ingest_session";

export async function resolveSessionStatus({ repository, artifacts, year, round, session }) {
  const sessionType = normalizeSessionCode(session);
  const sessionId = sessionIdFromParts(year, round, sessionType);
  const [sessionRow, manifest] = await Promise.all([
    repository.getSession(sessionId),
    artifacts.head(sessionManifestPath(sessionId))
  ]);
  // The manifest alone decides whether a publication completed. `summary.json`
  // used to count too, which was never sound -- it is one section among twenty,
  // written before the manifest that indexes them -- and under generations it is
  // actively wrong: session objects live under a generation prefix, so anything
  // still answering at the conventional summary path is a leftover of the old
  // layout or a static-export file, neither of which describes what R2 holds.
  if (manifest) {
    const readyValues = {
      session_id: sessionId,
      year: Number(year),
      round: Number(round),
      meeting_id: sessionRow?.meeting_id || null,
      meeting_name: sessionRow?.meeting_name || null,
      session_type: sessionType,
      scheduled_start: sessionRow?.scheduled_start || null,
      status: "ready",
      artifact_base_path: artifactBasePath(sessionId),
      generated_at: manifest.uploaded || sessionRow?.generated_at || null,
      source: sessionRow?.source || (manifest.source === "r2" ? "r2" : "static"),
      quality_json: sessionRow?.quality_json || null
    };

    // Which manifest this is decides whether D1 may be *written* from it.
    //
    // An R2-backed hit is authoritative: reaching the conventional manifest path
    // in R2 now means a pointer resolved it, and a pointer only exists after a
    // publication verified and committed. So it is safe to reconcile D1 to it --
    // including seeding a row that is missing entirely, which is how a session
    // whose success callback never landed recovers without a re-ingestion.
    //
    // A fallback-origin hit is not. It is the committed static export, which
    // says nothing about the bucket, so it may report readiness but must not
    // conjure a D1 row that later reads as authoritative history. An existing
    // row is still updated: something already established that session.
    const authoritative = manifest.source === "r2";
    let readySession;
    if (sessionMatches(sessionRow, readyValues)) {
      readySession = sessionRow;
    } else if (authoritative || sessionRow) {
      readySession = await repository.upsertSession(readyValues);
    } else {
      readySession = readyValues;
    }

    return statusResponse(readySession, "ready", {
      artifact_exists: true,
      artifact_path: manifest.key,
      size_bytes: manifest.size
    });
  }

  const activeJob = await repository.getActiveJob(sessionId, INGEST_SESSION);
  if (activeJob) {
    const activeValues = {
      session_id: sessionId,
      year: Number(year),
      round: Number(round),
      meeting_id: sessionRow?.meeting_id || null,
      meeting_name: sessionRow?.meeting_name || null,
      session_type: sessionType,
      scheduled_start: sessionRow?.scheduled_start || null,
      status: activeJob.status === "running" ? "ingesting" : "queued",
      artifact_base_path: artifactBasePath(sessionId),
      generated_at: sessionRow?.generated_at || null,
      source: sessionRow?.source || "dynamic"
    };
    const nextSession = sessionMatches(sessionRow, activeValues)
      ? sessionRow
      : await repository.upsertSession(activeValues);
    return statusResponse(nextSession, nextSession.status, {
      artifact_exists: false,
      job: activeJob
    });
  }

  if (sessionRow) {
    let resolvedSession = sessionRow;
    let sessionStatus = sessionRow.status || "missing";
    if (sessionStatus === "ready") {
      sessionStatus = "stale";
      resolvedSession = await repository.upsertSession({ ...sessionRow, status: sessionStatus });
    }
    const latestJob =
      sessionStatus === "failed" && typeof repository.getLatestJob === "function"
        ? await repository.getLatestJob(sessionId, INGEST_SESSION)
        : null;
    return statusResponse(resolvedSession, sessionStatus, {
      artifact_exists: false,
      job: latestJob
    });
  }

  const missing = {
    session_id: sessionId,
    year: Number(year),
    round: Number(round),
    meeting_id: null,
    meeting_name: null,
    session_type: sessionType,
    scheduled_start: null,
    status: "missing",
    artifact_base_path: artifactBasePath(sessionId),
    generated_at: null,
    source: "dynamic"
  };
  return statusResponse(missing, "missing", {
    artifact_exists: false
  });
}

export async function enqueueIngestionJob({
  repository,
  artifacts,
  queue,
  year,
  round,
  session,
  meetingId = null,
  meetingName = null,
  scheduledStart = null,
  force = false,
  now = new Date(),
  requestId = null
}) {
  const sessionType = normalizeSessionCode(session);
  const sessionId = sessionIdFromParts(year, round, sessionType);
  const current = await resolveSessionStatus({ repository, artifacts, year, round, session: sessionType });

  if (current.status === "ready" && !force) {
    return {
      action: "ready",
      status: current,
      job: null
    };
  }

  if (!force && current.job && ["queued", "running"].includes(current.job.status)) {
    return {
      action: "reused",
      status: current,
      job: current.job
    };
  }

  const existingSession = await repository.getSession(sessionId);
  const sessionRow = await repository.upsertSession({
    session_id: sessionId,
    year: Number(year),
    round: Number(round),
    meeting_id: meetingId || existingSession?.meeting_id || null,
    meeting_name: meetingName || existingSession?.meeting_name || null,
    session_type: sessionType,
    scheduled_start: scheduledStart || existingSession?.scheduled_start || null,
    status: "queued",
    artifact_base_path: artifactBasePath(sessionId),
    generated_at: existingSession?.generated_at || null,
    source: existingSession?.source || "dynamic"
  });

  const jobRequest = {
    job_id: makeJobId(INGEST_SESSION, sessionId, now),
    session_id: sessionId,
    kind: INGEST_SESSION,
    status: "queued",
    attempts: 0,
    error_message: null,
    created_at: now.toISOString(),
    started_at: null,
    finished_at: null,
    force
  };
  const job = await repository.createJob(jobRequest);
  if (!job) {
    const activeJob = await repository.getActiveJob(sessionId, INGEST_SESSION);
    if (!activeJob) {
      throw new Error("Failed to create or recover the active ingestion job");
    }
    return {
      action: "reused",
      status: statusResponse(sessionRow, activeJob.status === "running" ? "ingesting" : "queued", {
        artifact_exists: false,
        job: activeJob
      }),
      job: activeJob
    };
  }

  const message = queueMessageForJob({ ...job, force }, sessionRow);
  try {
    await queue.send(message);
    logLifecycle({
      requestId,
      jobId: job.job_id,
      sessionId,
      transition: "missing_or_terminal->queued",
      queueSend: "succeeded"
    });
  } catch (error) {
    const errorMessage = `Queue send failed: ${error instanceof Error ? error.message : String(error)}`;
    const finishedAt = new Date().toISOString();
    const transition = await repository.transitionJobAndSession(job.job_id, {
      status: "failed",
      error_message: errorMessage,
      finished_at: finishedAt
    }, {
      session_id: sessionId,
      status: "failed"
    });
    if (!transition) {
      throw new Error(`${errorMessage}; failed to persist the compensated state`);
    }
    logLifecycle({
      requestId,
      jobId: job.job_id,
      sessionId,
      transition: "queued->failed",
      queueSend: "failed",
      error: errorMessage
    });
    throw new Error(errorMessage);
  }

  return {
    action: "queued",
    status: statusResponse(sessionRow, "queued", {
      artifact_exists: false,
      job
    }),
    job,
    message
  };
}

export function statusResponse(session, status, details = {}) {
  return {
    session_id: session.session_id,
    year: Number(session.year),
    round: Number(session.round),
    meeting_id: session.meeting_id || null,
    meeting_name: session.meeting_name || null,
    session_type: session.session_type,
    scheduled_start: session.scheduled_start || null,
    status,
    artifact_base_path: session.artifact_base_path || artifactBasePath(session.session_id),
    generated_at: session.generated_at || null,
    source: session.source || "dynamic",
    quality: parseQuality(session.quality_json),
    artifact_exists: Boolean(details.artifact_exists),
    artifact_path: details.artifact_path || null,
    size_bytes: details.size_bytes ?? null,
    job: details.job || null
  };
}

function sessionMatches(current, expected) {
  if (!current) {
    return false;
  }
  return [
    "session_id",
    "year",
    "round",
    "meeting_id",
    "meeting_name",
    "session_type",
    "scheduled_start",
    "status",
    "artifact_base_path",
    "generated_at",
    "source",
    "quality_json"
  ].every((key) => String(current[key] ?? "") === String(expected[key] ?? ""));
}

function parseQuality(value) {
  if (!value) {
    return null;
  }
  if (typeof value === "object") {
    return value;
  }
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function logLifecycle({ requestId, jobId, sessionId, transition, queueSend, error = null }) {
  console.info(
    JSON.stringify({
      message: "ingestion lifecycle transition",
      request_id: requestId,
      job_id: jobId,
      session_id: sessionId,
      lifecycle_transition: transition,
      artifact_verification_result: "not_applicable",
      queue_send_result: queueSend,
      error
    })
  );
}
