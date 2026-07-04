export const SESSION_NAME_TO_CODE = {
  "practice 1": "FP1",
  "practice 2": "FP2",
  "practice 3": "FP3",
  "qualifying": "Q",
  "sprint qualifying": "SQ",
  "sprint shootout": "SQ",
  "sprint": "S",
  "race": "R"
};

export const ACTIVE_JOB_STATUSES = ["queued", "running"];

export function normalizeSessionCode(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    throw new Error("session is required");
  }
  return SESSION_NAME_TO_CODE[raw.toLowerCase()] || raw.toUpperCase();
}

export function sessionIdFromParts(year, round, session) {
  const parsedYear = Number.parseInt(String(year), 10);
  const parsedRound = Number.parseInt(String(round), 10);
  const code = normalizeSessionCode(session);
  if (!Number.isInteger(parsedYear) || parsedYear < 1950) {
    throw new Error("year must be a valid F1 season year");
  }
  if (!Number.isInteger(parsedRound) || parsedRound < 1) {
    throw new Error("round must be a positive integer");
  }
  return `${parsedYear}-${String(parsedRound).padStart(2, "0")}-${code.toLowerCase()}`;
}

export function artifactBasePath(sessionId) {
  return `sessions/${sessionId}`;
}

export function sessionManifestPath(sessionId) {
  return `${artifactBasePath(sessionId)}/manifest.json`;
}

export function sessionSummaryPath(sessionId) {
  return `${artifactBasePath(sessionId)}/summary.json`;
}

export function sanitizeArtifactPath(pathname) {
  let artifactPath = decodeURIComponent(String(pathname || ""));
  artifactPath = artifactPath.replace(/^\/+/, "");
  artifactPath = artifactPath.replace(/^data\/+/, "");
  artifactPath = artifactPath.replace(/\\/g, "/");

  if (!artifactPath || artifactPath.includes("\0")) {
    throw new Error("artifact path is empty");
  }
  if (artifactPath.split("/").some((part) => part === "..")) {
    throw new Error("artifact path cannot contain parent directory segments");
  }
  return artifactPath;
}

export function makeJobId(kind, sessionId, date = new Date(), randomId = randomSuffix()) {
  const timestamp = date.toISOString().replace(/[-:.TZ]/g, "");
  return `${kind}:${sessionId}:${timestamp}:${randomId}`;
}

export function queueMessageForJob(job, session) {
  return {
    version: 1,
    job_id: job.job_id,
    kind: job.kind,
    session_id: session.session_id,
    year: session.year,
    round: session.round,
    session: session.session_type,
    meeting_id: session.meeting_id || null,
    meeting_name: session.meeting_name || null,
    artifact_base_path: session.artifact_base_path || artifactBasePath(session.session_id),
    force: Boolean(job.force),
    requested_at: job.created_at
  };
}

function randomSuffix() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID().slice(0, 8);
  }
  return Math.random().toString(36).slice(2, 10);
}
