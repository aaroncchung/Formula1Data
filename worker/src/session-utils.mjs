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

export const SESSION_CODES = new Set(["FP1", "FP2", "FP3", "Q", "SQ", "S", "R"]);

export function normalizeSessionCode(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    throw new Error("session is required");
  }
  const code = SESSION_NAME_TO_CODE[raw.toLowerCase()] || raw.toUpperCase();
  if (!SESSION_CODES.has(code)) {
    throw new Error("session must be FP1, FP2, FP3, Q, SQ, S, or R");
  }
  return code;
}

export function sessionIdFromParts(year, round, session) {
  const parsedYear = Number.parseInt(String(year), 10);
  const parsedRound = Number.parseInt(String(round), 10);
  const code = normalizeSessionCode(session);
  if (!/^\d{4}$/.test(String(year).trim()) || !Number.isInteger(parsedYear) || parsedYear < 1950 || parsedYear > 2100) {
    throw new Error("year must be a valid F1 season year");
  }
  if (!/^\d{1,2}$/.test(String(round).trim()) || !Number.isInteger(parsedRound) || parsedRound < 1 || parsedRound > 30) {
    throw new Error("round must be an integer from 1 to 30");
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
  let artifactPath;
  try {
    artifactPath = decodeURIComponent(String(pathname || ""));
  } catch {
    throw new Error("artifact path contains invalid encoding");
  }
  artifactPath = artifactPath.replace(/^\/+/, "");
  artifactPath = artifactPath.replace(/^data\/+/, "");
  artifactPath = artifactPath.replace(/\\/g, "/");

  if (!artifactPath) {
    throw new Error("artifact path is empty");
  }
  if (new TextEncoder().encode(artifactPath).byteLength > 1024 || artifactPath.includes("\0")) {
    throw new Error("artifact path is invalid");
  }
  const segments = artifactPath.split("/");
  if (segments.some((part) => part === "..")) {
    throw new Error("artifact path cannot contain parent directory segments");
  }
  if (segments.some((part) => !part || part === ".")) {
    throw new Error("artifact path contains invalid segments");
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
  if (!globalThis.crypto?.randomUUID) {
    throw new Error("secure random UUID generation is unavailable");
  }
  return globalThis.crypto.randomUUID().slice(0, 8);
}
