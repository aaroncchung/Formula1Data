import { sanitizeArtifactPath } from "./session-utils.mjs";

const MAX_VERIFIED_ARTIFACT_BYTES = 8 * 1024 * 1024;

export function createArtifactStore(env) {
  return {
    async head(path) {
      const key = sanitizeArtifactPath(path);
      if (env.ARTIFACTS_BUCKET?.head) {
        const object = await env.ARTIFACTS_BUCKET.head(key);
        if (object) {
          return {
            key,
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
        const object = await env.ARTIFACTS_BUCKET.head(key);
        if (object) {
          return r2ObjectResponse(object, key, true, request?.headers);
        }
      } else if (env.ARTIFACTS_BUCKET?.get) {
        const options = r2GetOptions(request?.headers);
        const object = await env.ARTIFACTS_BUCKET.get(key, options);
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
      const key = sanitizeArtifactPath(record.path);
      const loaded = await loadArtifactBytes(env, key, r2Only);
      if (!loaded) {
        return { verified: false, key, source: r2Only ? "r2" : null, reason: "missing" };
      }
      if (loaded.bytes.byteLength !== record.size_bytes) {
        return {
          verified: false,
          key,
          source: loaded.source,
          reason: "size_mismatch",
          actual_size_bytes: loaded.bytes.byteLength
        };
      }
      const checksum = await sha256Checksum(loaded.bytes);
      return {
        verified: checksum === record.checksum,
        key,
        source: loaded.source,
        reason: checksum === record.checksum ? null : "checksum_mismatch",
        actual_size_bytes: loaded.bytes.byteLength,
        actual_checksum: checksum
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

async function loadArtifactBytes(env, key, r2Only) {
  if (env.ARTIFACTS_BUCKET?.get) {
    const object = await env.ARTIFACTS_BUCKET.get(key);
    if (object?.body) {
      if (Number(object.size) > MAX_VERIFIED_ARTIFACT_BYTES) {
        throw new Error(`Artifact ${key} exceeds the verification size limit`);
      }
      const bytes = new Uint8Array(await new Response(object.body).arrayBuffer());
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
  if (Number.isFinite(declaredSize) && declaredSize > MAX_VERIFIED_ARTIFACT_BYTES) {
    await response.body?.cancel();
    throw new Error(`Artifact ${key} exceeds the verification size limit`);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > MAX_VERIFIED_ARTIFACT_BYTES) {
    throw new Error(`Artifact ${key} exceeds the verification size limit`);
  }
  return { bytes, source: "fallback" };
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
