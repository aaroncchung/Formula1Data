import {
  artifactBasePath,
  makeJobId,
  normalizeSessionCode,
  queueMessageForJob,
  sessionIdFromParts,
  sessionManifestPath,
  sessionSummaryPath
} from "./session-utils.mjs";

export const INGEST_SESSION = "ingest_session";

export async function resolveSessionStatus({ repository, artifacts, year, round, session }) {
  const sessionType = normalizeSessionCode(session);
  const sessionId = sessionIdFromParts(year, round, sessionType);
  const [sessionRow, manifest] = await Promise.all([
    repository.getSession(sessionId),
    artifacts.head(sessionManifestPath(sessionId))
  ]);
  const artifact = manifest || (await artifacts.head(sessionSummaryPath(sessionId)));

  if (artifact) {
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
      generated_at: artifact.uploaded || sessionRow?.generated_at || null,
      source: sessionRow?.source || "r2"
    };
    const readySession = sessionMatches(sessionRow, readyValues)
      ? sessionRow
      : await repository.upsertSession(readyValues);
    return statusResponse(readySession, "ready", {
      artifact_exists: true,
      artifact_path: artifact.key,
      size_bytes: artifact.size
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
    const sessionStatus = sessionRow.status || "missing";
    const latestJob =
      sessionStatus === "failed" && typeof repository.getLatestJob === "function"
        ? await repository.getLatestJob(sessionId, INGEST_SESSION)
        : null;
    return statusResponse(sessionRow, sessionStatus, {
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
  now = new Date()
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
  await queue.send(message);

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
    "source"
  ].every((key) => String(current[key] ?? "") === String(expected[key] ?? ""));
}
