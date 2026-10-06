import { serveR2Object } from "./r2-response.mjs";
import { sanitizeArtifactPath } from "./session-utils.mjs";

const MAX_VERIFIED_ARTIFACT_BYTES = 8 * 1024 * 1024;

// A fallback origin answers a conditional or ranged request with a status that is
// not `ok` but still carries the answer the client asked for. Treating those as a
// miss turns them into a 404, so both `head()` and `get()` accept the same set.
const CONDITIONAL_FALLBACK_STATUSES = new Set([304, 416]);
const NULL_BODY_STATUSES = new Set([204, 205, 304]);

function isAcceptableFallback(response) {
  return Boolean(response) && (response.ok || CONDITIONAL_FALLBACK_STATUSES.has(response.status));
}

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
      if (isAcceptableFallback(fallback)) {
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
      const stored = await serveR2Object(env.ARTIFACTS_BUCKET, key, request, cacheControlForKey(key));
      if (stored) {
        return stored;
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
