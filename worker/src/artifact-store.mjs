import { sanitizeArtifactPath } from "./session-utils.mjs";

const MAX_MANIFEST_BYTES = 1024 * 1024;
const MAX_MANIFEST_SECTIONS = 5_000;
const MAX_ACTIVE_POINTER_BYTES = 4 * 1024;

// `sessions/<id>/active.json` names the generation a session is currently
// published as. Everything else under `sessions/<id>/` is addressed through it,
// which is what lets the publisher write immutable generations while the
// frontend keeps building `sessions/<id>/summary.json` by convention.
const SESSION_KEY = /^sessions\/([^/]+)\/(.+)$/;
const SESSION_MANIFEST_KEY = /^sessions\/([^/]+)\/manifest\.json$/;
const GENERATION_ID = /^[a-f0-9]{64}$/;

// A fallback origin answers a conditional or ranged request with a status that is
// not `ok` but still carries the answer the client asked for. Treating those as a
// miss turns them into a 404, so both `head()` and `get()` accept the same set.
const CONDITIONAL_FALLBACK_STATUSES = new Set([304, 416]);
const NULL_BODY_STATUSES = new Set([204, 205, 304]);

function isAcceptableFallback(response) {
  return Boolean(response) && (response.ok || CONDITIONAL_FALLBACK_STATUSES.has(response.status));
}

export function createArtifactStore(env) {
  // One resolver per store, not per call: a session page reads twenty artifacts
  // and a telemetry-heavy one far more, and they all resolve through the same
  // pointer. Building the resolver inside each method would make its memo
  // useless and cost an extra R2 GET on every single artifact read.
  const resolveKey = createR2KeyResolver(env);

  return {
    async head(path) {
      const key = sanitizeArtifactPath(path);
      if (env.ARTIFACTS_BUCKET?.head) {
        const storageKey = await resolveKey(key);
        const object = await env.ARTIFACTS_BUCKET.head(storageKey);
        if (object) {
          return {
            key,
            storage_key: storageKey,
            source: "r2",
            size: object.size ?? null,
            etag: object.httpEtag || null,
            uploaded: object.uploaded ? object.uploaded.toISOString() : null
          };
        }
      }

      // The fallback origin serves the conventional layout, so it is always
      // addressed by `key` rather than the resolved generation key.
      const fallback = await fetchFallback(env, key, { method: "HEAD" });
      if (isAcceptableFallback(fallback)) {
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
      if (method === "HEAD" && env.ARTIFACTS_BUCKET?.head) {
        const object = await env.ARTIFACTS_BUCKET.head(await resolveKey(key));
        if (object) {
          return r2ObjectResponse(object, key, true, request?.headers);
        }
      } else if (env.ARTIFACTS_BUCKET?.get) {
        const options = r2GetOptions(request?.headers);
        const object = await env.ARTIFACTS_BUCKET.get(await resolveKey(key), options);
        if (object) {
          return r2ObjectResponse(object, key, false, request?.headers);
        }
      }

      const fallback = await fetchFallback(env, key, {
        method,
        headers: forwardedRequestHeaders(request?.headers)
      });
      if (isAcceptableFallback(fallback)) {
        const headers = new Headers(fallback.headers);
        headers.set("cache-control", cacheControlForKey(key));
        headers.set("accept-ranges", "bytes");
        const body = NULL_BODY_STATUSES.has(fallback.status) ? null : fallback.body;
        return new Response(body, {
          status: fallback.status,
          statusText: fallback.statusText,
          headers
        });
      }
      return null;
    },

    /**
     * Verify a session's manifest against the generation the pointer names.
     *
     * It is not enough to ask whether some key holds the promised bytes. The
     * question a success callback has to answer is whether the generation the
     * publisher says it committed is the one that is actually live, so this
     * fails closed on a pointer it cannot read, and insists the pointer's own
     * manifest metadata agrees with the record the callback carried. A job
     * cannot report success against a manifest that is not the live one.
     *
     * R2 only, always: the fallback origin serves the conventional layout and
     * has no pointer, so it cannot answer this question at all.
     */
    async verifyManifest(record) {
      const key = sanitizeArtifactPath(record?.path || "");
      const match = key.match(SESSION_MANIFEST_KEY);
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
        loaded = await loadR2Bytes(env, key, `${active.base}/manifest.json`, MAX_MANIFEST_BYTES);
      } catch (error) {
        return {
          verified: false,
          key,
          source: "r2",
          reason: "verification_error",
          error: error instanceof Error ? error.message : String(error)
        };
      }
      if (!loaded) {
        return { verified: false, key, source: "r2", reason: "missing" };
      }
      if (loaded.bytes.byteLength !== record.size_bytes) {
        return {
          verified: false,
          key,
          source: "r2",
          reason: "size_mismatch",
          actual_size_bytes: loaded.bytes.byteLength
        };
      }
      const checksum = await sha256Checksum(loaded.bytes);
      if (checksum !== record.checksum) {
        return {
          verified: false,
          key,
          source: "r2",
          reason: "checksum_mismatch",
          actual_size_bytes: loaded.bytes.byteLength,
          actual_checksum: checksum
        };
      }

      let manifest;
      try {
        manifest = JSON.parse(new TextDecoder().decode(loaded.bytes));
      } catch {
        return { verified: false, key, source: "r2", reason: "invalid_manifest_json" };
      }
      const validation = validateManifest(manifest, match[1]);
      if (!validation.valid) {
        return { verified: false, key, source: "r2", reason: validation.reason };
      }

      return {
        verified: true,
        key,
        storage_key: `${active.base}/manifest.json`,
        source: "r2",
        reason: null,
        generation_id: active.generationId,
        actual_size_bytes: loaded.bytes.byteLength,
        actual_checksum: checksum,
        artifact_count: validation.sectionCount
      };
    }
  };
}

/**
 * Map a conventional session key onto the key that currently holds its bytes.
 *
 * Fails open, deliberately. A pointer that is absent, oversized or malformed
 * resolves to the conventional key, and that cannot serve the wrong generation:
 * under this layout a generation-published session has no object at its
 * conventional key, so the read simply misses. Legacy sessions published before
 * generations existed are exactly the case where the conventional key is
 * correct. Failing closed instead would take a whole session offline over one
 * unreadable 200-byte object.
 *
 * `verifyManifest` makes the opposite choice, because there a pointer it cannot
 * read is the very thing it exists to check.
 */
function createR2KeyResolver(env) {
  const pointers = new Map();
  return async (key) => {
    const match = key.match(SESSION_KEY);
    if (
      !match ||
      match[2] === "active.json" ||
      match[2].startsWith("generations/") ||
      !env.ARTIFACTS_BUCKET?.get
    ) {
      return key;
    }
    const sessionId = match[1];
    if (!pointers.has(sessionId)) {
      pointers.set(
        sessionId,
        await loadActivePointer(env, sessionId).catch(() => null)
      );
    }
    const active = pointers.get(sessionId);
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
  // Checked before and after reading: `size` is metadata a caller could have
  // written, so it screens the obvious case cheaply, and the post-read length
  // is what actually bounds memory.
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
    !GENERATION_ID.test(generationId) ||
    !isManifestMetadata(pointer?.manifest) ||
    // The generation is named by its manifest's checksum, so a pointer whose id
    // and manifest checksum disagree is internally inconsistent whatever else
    // it says, and there is no safe way to guess which half is right.
    generationId !== pointer.manifest.checksum.slice("sha256:".length)
  ) {
    throw new Error(`Active generation pointer for ${sessionId} is invalid`);
  }
  return { pointer, base, generationId };
}

function isManifestMetadata(value) {
  return Boolean(
    value &&
      typeof value === "object" &&
      Number.isInteger(value.size_bytes) &&
      value.size_bytes >= 0 &&
      typeof value.checksum === "string" &&
      /^sha256:[a-f0-9]{64}$/.test(value.checksum)
  );
}

function isArtifactRecord(record) {
  return Boolean(
    record &&
      typeof record === "object" &&
      Number.isInteger(record.size_bytes) &&
      record.size_bytes >= 0 &&
      typeof record.checksum === "string" &&
      /^sha256:[a-f0-9]{64}$/.test(record.checksum)
  );
}

function validateManifest(manifest, sessionId) {
  if (!manifest || typeof manifest !== "object") {
    return { valid: false, reason: "invalid_manifest_json" };
  }
  if (manifest.session_id !== sessionId) {
    return { valid: false, reason: "manifest_session_mismatch" };
  }
  const sections = manifest.sections;
  if (!Array.isArray(sections)) {
    return { valid: false, reason: "invalid_manifest_sections" };
  }
  // A bound rather than a limit anyone should reach: the largest committed
  // session runs to roughly a thousand telemetry laps. It exists so a hostile
  // or corrupt manifest cannot make this loop unbounded work.
  if (sections.length > MAX_MANIFEST_SECTIONS) {
    return { valid: false, reason: "manifest_too_large" };
  }
  const expectedPrefix = `sessions/${sessionId}/`;
  for (const section of sections) {
    if (!section || typeof section !== "object") {
      return { valid: false, reason: "invalid_manifest_sections" };
    }
    const path = String(section.path || "");
    if (!path.startsWith(expectedPrefix) || path.includes("..")) {
      return { valid: false, reason: "invalid_manifest_sections" };
    }
  }
  if (!sections.some((section) => section.kind === "summary")) {
    return { valid: false, reason: "manifest_missing_summary" };
  }
  return { valid: true, sectionCount: sections.length };
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

// R2 only, with no fallback branch: the one caller is manifest verification,
// and the fallback origin serves the conventional layout with no pointer, so it
// cannot answer which generation is live. `key` names the artifact in errors;
// `storageKey` is where the bytes actually are.
async function loadR2Bytes(env, key, storageKey, maxBytes) {
  if (!env.ARTIFACTS_BUCKET?.get) {
    return null;
  }
  const object = await env.ARTIFACTS_BUCKET.get(storageKey);
  if (!object?.body) {
    return null;
  }
  if (Number(object.size) > maxBytes) {
    await object.body.cancel();
    throw new Error(`Artifact ${key} exceeds the verification size limit`);
  }
  const bytes = new Uint8Array(await new Response(object.body).arrayBuffer());
  if (bytes.byteLength > maxBytes) {
    throw new Error(`Artifact ${key} exceeds the verification size limit`);
  }
  return { bytes, source: "r2" };
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
