import { sanitizeArtifactPath } from "./session-utils.mjs";

const MAX_VERIFIED_ARTIFACT_BYTES = 8 * 1024 * 1024;
const MAX_MANIFEST_BYTES = 1024 * 1024;
const MAX_MANIFEST_SECTIONS = 5_000;
const MAX_ACTIVE_POINTER_BYTES = 4 * 1024;

export function createArtifactStore(env) {
  return {
    async head(path) {
      const key = sanitizeArtifactPath(path);
      if (env.ARTIFACTS_BUCKET?.head) {
        const r2Key = await createR2KeyResolver(env)(key);
        const object = await env.ARTIFACTS_BUCKET.head(r2Key);
        if (object) {
          return {
            key,
            storage_key: r2Key,
            source: "r2",
            size: object.size ?? null,
            etag: object.httpEtag || null,
            uploaded: object.uploaded ? object.uploaded.toISOString() : null
          };
        }
      }

      const fallback = await fetchFallback(env, key, { method: "HEAD" });
      if (fallback && (fallback.ok || fallback.status === 304 || fallback.status === 416)) {
        return {
          key,
          storage_key: key,
          source: "fallback",
          size: numberOrNull(fallback.headers.get("content-length")),
          etag: fallback.headers.get("etag"),
          uploaded: fallback.headers.get("last-modified")
        };
      }
      return null;
    },

    async get(path, request = null) {
      const key = sanitizeArtifactPath(path);
      const method = request?.method === "HEAD" ? "HEAD" : "GET";
      const resolveR2Key = createR2KeyResolver(env);
      if (method === "HEAD" && env.ARTIFACTS_BUCKET?.head) {
        const object = await env.ARTIFACTS_BUCKET.head(await resolveR2Key(key));
        if (object) {
          return r2ObjectResponse(object, key, true, request?.headers);
        }
      } else if (env.ARTIFACTS_BUCKET?.get) {
        const options = r2GetOptions(request?.headers);
        const object = await env.ARTIFACTS_BUCKET.get(await resolveR2Key(key), options);
        if (object) {
          return r2ObjectResponse(object, key, false, request?.headers);
        }
      }

      const fallback = await fetchFallback(env, key, {
        method,
        headers: forwardedRequestHeaders(request?.headers)
      });
      if (fallback?.ok) {
        const headers = new Headers(fallback.headers);
        headers.set("cache-control", cacheControlForKey(key));
        headers.set("accept-ranges", "bytes");
        return new Response(fallback.body, {
          status: fallback.status,
          statusText: fallback.statusText,
          headers
        });
      }
      return null;
    },

    async verify(record, { r2Only = false } = {}) {
      return verifyArtifactRecord(env, record, r2Only, createR2KeyResolver(env));
    },

    async verifyManifest(record) {
      const key = sanitizeArtifactPath(record.path);
      const match = key.match(/^sessions\/([^/]+)\/manifest\.json$/);
      if (!match || !isArtifactRecord(record)) {
        return { verified: false, key, source: "r2", reason: "invalid_manifest_record" };
      }

      let active;
      try {
        active = await loadActivePointer(env, match[1]);
      } catch (error) {
        return {
          verified: false,
          key,
          source: "r2",
          reason: "invalid_active_pointer",
          error: error instanceof Error ? error.message : String(error)
        };
      }
      if (!active) {
        return { verified: false, key, source: "r2", reason: "missing_active_pointer" };
      }
      if (
        active.pointer.manifest.size_bytes !== record.size_bytes ||
        active.pointer.manifest.checksum !== record.checksum
      ) {
        return { verified: false, key, source: "r2", reason: "active_manifest_mismatch" };
      }

      let loaded;
      try {
        loaded = await loadVerifiedArtifact(
          env,
          record,
          true,
          async () => `${active.base}/manifest.json`,
          MAX_MANIFEST_BYTES
        );
      } catch (error) {
        return {
          verified: false,
          key,
          source: "r2",
          reason: "verification_error",
          error: error instanceof Error ? error.message : String(error)
        };
      }
      if (!loaded.verification.verified) {
        return loaded.verification;
      }

      let manifest;
      try {
        manifest = JSON.parse(new TextDecoder().decode(loaded.bytes));
      } catch {
        return { ...loaded.verification, verified: false, reason: "invalid_manifest_json" };
      }
      const validation = validateManifest(manifest, record.path);
      if (!validation.valid) {
        return { ...loaded.verification, verified: false, reason: validation.reason };
      }

      return {
        ...loaded.verification,
        artifact_count: validation.sections.length
      };
    }
  };
}

export function cacheControlForKey(key) {
  if (key.startsWith("sessions/")) {
    return "public, max-age=30, stale-while-revalidate=300";
  }
  return "public, max-age=120, stale-while-revalidate=600";
}

async function fetchFallback(env, key, init) {
  const baseUrl = env.STATIC_DATA_BASE_URL || env.LOCAL_STATIC_DATA_BASE_URL;
  if (!baseUrl) {
    return null;
  }

  const url = fallbackUrl(baseUrl, key);
  const response = await fetch(url, init);
  if (response.status === 405 && init.method === "HEAD") {
    const ranged = await fetch(url, {
      method: "GET",
      headers: { range: "bytes=0-0" }
    });
    await ranged.body?.cancel();
    const headers = new Headers(ranged.headers);
    const totalSize = totalSizeFromContentRange(headers.get("content-range"));
    if (totalSize !== null) {
      headers.set("content-length", String(totalSize));
    }
    headers.delete("content-range");
    return new Response(null, { status: ranged.ok ? 200 : ranged.status, headers });
  }
  return response;
}

function fallbackUrl(baseUrl, key) {
  const normalizedBase = String(baseUrl).endsWith("/") ? String(baseUrl) : `${baseUrl}/`;
  return new URL(key, normalizedBase);
}

function createR2KeyResolver(env) {
  const activePointers = new Map();
  return async (key) => {
    const match = key.match(/^sessions\/([^/]+)\/(.+)$/);
    if (!match || match[2] === "active.json" || match[2].startsWith("generations/") || !env.ARTIFACTS_BUCKET?.get) {
      return key;
    }
    const sessionId = match[1];
    if (!activePointers.has(sessionId)) {
      activePointers.set(sessionId, await loadActivePointer(env, sessionId));
    }
    const active = activePointers.get(sessionId);
    return active ? `${active.base}/${match[2]}` : key;
  };
}

async function loadActivePointer(env, sessionId) {
  if (!env.ARTIFACTS_BUCKET?.get) {
    return null;
  }
  const object = await env.ARTIFACTS_BUCKET.get(`sessions/${sessionId}/active.json`);
  if (!object?.body) {
    return null;
  }
  if (Number(object.size) > MAX_ACTIVE_POINTER_BYTES) {
    await object.body.cancel();
    throw new Error(`Active generation pointer for ${sessionId} is too large`);
  }
  const bytes = new Uint8Array(await new Response(object.body).arrayBuffer());
  if (bytes.byteLength > MAX_ACTIVE_POINTER_BYTES) {
    throw new Error(`Active generation pointer for ${sessionId} is too large`);
  }

  let pointer;
  try {
    pointer = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new Error(`Active generation pointer for ${sessionId} is invalid`);
  }
  const base = String(pointer?.artifact_base_path || "");
  const expectedPrefix = `sessions/${sessionId}/generations/`;
  const generationId = base.startsWith(expectedPrefix) ? base.slice(expectedPrefix.length) : "";
  if (
    pointer?.schema_version !== 1 ||
    pointer?.session_id !== sessionId ||
    !/^[a-f0-9]{64}$/.test(generationId) ||
    !isManifestMetadata(pointer?.manifest) ||
    generationId !== pointer.manifest.checksum.slice("sha256:".length)
  ) {
    throw new Error(`Active generation pointer for ${sessionId} is invalid`);
  }
  return { pointer, base };
}

function isManifestMetadata(value) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Number.isSafeInteger(value.size_bytes) &&
    value.size_bytes >= 0 &&
    typeof value.checksum === "string" &&
    /^sha256:[a-f0-9]{64}$/.test(value.checksum)
  );
}

async function loadArtifactBytes(
  env,
  key,
  r2Only,
  resolveR2Key,
  maxBytes = MAX_VERIFIED_ARTIFACT_BYTES
) {
  if (env.ARTIFACTS_BUCKET?.get) {
    const object = await env.ARTIFACTS_BUCKET.get(await resolveR2Key(key));
    if (object?.body) {
      if (Number(object.size) > maxBytes) {
        throw new Error(`Artifact ${key} exceeds the verification size limit`);
      }
      const bytes = new Uint8Array(await new Response(object.body).arrayBuffer());
      if (bytes.byteLength > maxBytes) {
        throw new Error(`Artifact ${key} exceeds the verification size limit`);
      }
      return { bytes, source: "r2" };
    }
  }
  if (r2Only) {
    return null;
  }
  const response = await fetchFallback(env, key, { method: "GET" });
  if (!response?.ok) {
    return null;
  }
  const declaredSize = Number.parseInt(response.headers.get("content-length") || "", 10);
  if (Number.isFinite(declaredSize) && declaredSize > maxBytes) {
    await response.body?.cancel();
    throw new Error(`Artifact ${key} exceeds the verification size limit`);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > maxBytes) {
    throw new Error(`Artifact ${key} exceeds the verification size limit`);
  }
  return { bytes, source: "fallback" };
}

async function verifyArtifactRecord(env, record, r2Only, resolveR2Key) {
  const loaded = await loadVerifiedArtifact(env, record, r2Only, resolveR2Key);
  return loaded.verification;
}

async function loadVerifiedArtifact(
  env,
  record,
  r2Only,
  resolveR2Key,
  maxBytes = MAX_VERIFIED_ARTIFACT_BYTES
) {
  const key = sanitizeArtifactPath(record.path);
  const loaded = await loadArtifactBytes(env, key, r2Only, resolveR2Key, maxBytes);
  if (!loaded) {
    return {
      bytes: null,
      verification: { verified: false, key, source: r2Only ? "r2" : null, reason: "missing" }
    };
  }
  if (loaded.bytes.byteLength !== record.size_bytes) {
    return {
      bytes: loaded.bytes,
      verification: {
        verified: false,
        key,
        source: loaded.source,
        reason: "size_mismatch",
        actual_size_bytes: loaded.bytes.byteLength
      }
    };
  }
  const checksum = await sha256Checksum(loaded.bytes);
  return {
    bytes: loaded.bytes,
    verification: {
      verified: checksum === record.checksum,
      key,
      source: loaded.source,
      reason: checksum === record.checksum ? null : "checksum_mismatch",
      actual_size_bytes: loaded.bytes.byteLength,
      actual_checksum: checksum
    }
  };
}

function validateManifest(manifest, manifestPath) {
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    return { valid: false, reason: "invalid_manifest" };
  }
  const sessionId = String(manifest.session_id || "");
  const expectedManifestPath = `sessions/${sessionId}/manifest.json`;
  if (
    manifest.schema_version !== 1 ||
    !sessionId ||
    manifestPath !== expectedManifestPath ||
    !Array.isArray(manifest.sections)
  ) {
    return { valid: false, reason: "invalid_manifest" };
  }
  if (manifest.sections.length > MAX_MANIFEST_SECTIONS) {
    return { valid: false, reason: "manifest_too_large" };
  }

  const prefix = `sessions/${sessionId}/`;
  const paths = new Set();
  let hasSummary = false;
  for (const section of manifest.sections) {
    if (!isArtifactRecord(section) || !section.path.startsWith(prefix) || paths.has(section.path)) {
      return { valid: false, reason: "invalid_manifest_section" };
    }
    try {
      if (sanitizeArtifactPath(section.path) !== section.path) {
        return { valid: false, reason: "invalid_manifest_section" };
      }
    } catch {
      return { valid: false, reason: "invalid_manifest_section" };
    }
    paths.add(section.path);
    hasSummary ||= section.kind === "summary";
  }
  if (!hasSummary) {
    return { valid: false, reason: "manifest_missing_summary" };
  }
  return { valid: true, sections: manifest.sections };
}

function isArtifactRecord(record) {
  return (
    record &&
    typeof record === "object" &&
    !Array.isArray(record) &&
    typeof record.kind === "string" &&
    typeof record.path === "string" &&
    Number.isSafeInteger(record.size_bytes) &&
    record.size_bytes >= 0 &&
    typeof record.checksum === "string" &&
    /^sha256:[a-f0-9]{64}$/.test(record.checksum)
  );
}

async function sha256Checksum(bytes) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function r2GetOptions(headers) {
  if (!headers) {
    return undefined;
  }
  const options = {};
  if (headers.has("range")) {
    options.range = headers;
  }
  if (
    headers.has("if-match") ||
    headers.has("if-none-match") ||
    headers.has("if-modified-since") ||
    headers.has("if-unmodified-since")
  ) {
    options.onlyIf = headers;
  }
  return Object.keys(options).length ? options : undefined;
}

function r2ObjectResponse(object, key, headOnly, requestHeaders) {
  const headers = new Headers();
  object.writeHttpMetadata?.(headers);
  if (!headers.has("content-type")) {
    headers.set("content-type", contentTypeForKey(key));
  }
  if (object.httpEtag) {
    headers.set("etag", object.httpEtag);
  }
  if (object.uploaded instanceof Date) {
    headers.set("last-modified", object.uploaded.toUTCString());
  }
  headers.set("cache-control", cacheControlForKey(key));
  headers.set("accept-ranges", "bytes");

  const preconditionStatus = failedPreconditionStatus(object, requestHeaders);
  if (preconditionStatus !== null) {
    headers.delete("content-length");
    return new Response(null, { status: preconditionStatus, headers });
  }

  if (headOnly) {
    headers.set("content-length", String(object.size));
    return new Response(null, { status: 200, headers });
  }

  if (!object.body) {
    headers.delete("content-length");
    const status = requestHeaders?.has("if-match") || requestHeaders?.has("if-unmodified-since") ? 412 : 304;
    return new Response(null, { status, headers });
  }

  const range = object.range;
  if (range && Number.isFinite(range.offset) && Number.isFinite(range.length)) {
    const end = range.offset + range.length - 1;
    headers.set("content-range", `bytes ${range.offset}-${end}/${object.size}`);
    headers.set("content-length", String(range.length));
    return new Response(object.body, { status: 206, headers });
  }
  headers.set("content-length", String(object.size));
  return new Response(object.body, { status: 200, headers });
}

function forwardedRequestHeaders(headers) {
  const forwarded = new Headers();
  for (const name of ["range", "if-match", "if-none-match", "if-modified-since", "if-unmodified-since"]) {
    const value = headers?.get(name);
    if (value) {
      forwarded.set(name, value);
    }
  }
  return forwarded;
}

function contentTypeForKey(key) {
  if (key.endsWith(".json")) {
    return "application/json; charset=utf-8";
  }
  if (key.endsWith(".csv")) {
    return "text/csv; charset=utf-8";
  }
  if (key.endsWith(".gz")) {
    return "application/gzip";
  }
  return "application/octet-stream";
}

function failedPreconditionStatus(object, headers) {
  if (!headers) {
    return null;
  }
  const etag = object.httpEtag;
  const ifMatch = headers.get("if-match");
  if (ifMatch && etag && !etagListMatches(ifMatch, etag)) {
    return 412;
  }
  const uploadedAt = object.uploaded instanceof Date ? object.uploaded.getTime() : null;
  const ifUnmodifiedSince = Date.parse(headers.get("if-unmodified-since") || "");
  if (!ifMatch && uploadedAt !== null && Number.isFinite(ifUnmodifiedSince) && uploadedAt > ifUnmodifiedSince) {
    return 412;
  }
  const ifNoneMatch = headers.get("if-none-match");
  if (ifNoneMatch && etag) {
    return etagListMatches(ifNoneMatch, etag) ? 304 : null;
  }
  const ifModifiedSince = Date.parse(headers.get("if-modified-since") || "");
  if (uploadedAt !== null && Number.isFinite(ifModifiedSince) && uploadedAt <= ifModifiedSince) {
    return 304;
  }
  return null;
}

function etagListMatches(headerValue, etag) {
  return String(headerValue)
    .split(",")
    .map((value) => value.trim())
    .some((value) => value === "*" || value === etag || value.replace(/^W\//, "") === etag);
}

function totalSizeFromContentRange(value) {
  const match = String(value || "").match(/\/([0-9]+)$/);
  if (!match) {
    return null;
  }
  return numberOrNull(match[1]);
}

function numberOrNull(value) {
  if (!value) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}
