import { sanitizeArtifactPath } from "./session-utils.mjs";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8"
};

export function createArtifactStore(env) {
  return {
    async head(path) {
      const key = sanitizeArtifactPath(path);
      if (env.ARTIFACTS_BUCKET?.head) {
        const object = await env.ARTIFACTS_BUCKET.head(key);
        if (object) {
          return {
            key,
            size: object.size || null,
            etag: object.httpEtag || null,
            uploaded: object.uploaded ? object.uploaded.toISOString() : null
          };
        }
      }

      const fallback = await fetchFallback(env, key, { method: "HEAD" });
      if (fallback?.ok) {
        return {
          key,
          size: numberOrNull(fallback.headers.get("content-length")),
          etag: fallback.headers.get("etag"),
          uploaded: fallback.headers.get("last-modified")
        };
      }
      return null;
    },

    async get(path) {
      const key = sanitizeArtifactPath(path);
      if (env.ARTIFACTS_BUCKET?.get) {
        const object = await env.ARTIFACTS_BUCKET.get(key);
        if (object) {
          const headers = new Headers(JSON_HEADERS);
          object.writeHttpMetadata?.(headers);
          headers.set("etag", object.httpEtag || headers.get("etag") || "");
          headers.set("cache-control", cacheControlForKey(key));
          return new Response(object.body, { headers });
        }
      }

      const fallback = await fetchFallback(env, key, { method: "GET" });
      if (fallback?.ok) {
        const headers = new Headers(fallback.headers);
        headers.set("cache-control", cacheControlForKey(key));
        return new Response(fallback.body, {
          status: fallback.status,
          headers
        });
      }
      return null;
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

  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/${key}`, init);
  if (response.status === 405 && init.method === "HEAD") {
    return fetch(`${baseUrl.replace(/\/$/, "")}/${key}`, { method: "GET" });
  }
  return response;
}

function numberOrNull(value) {
  if (!value) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}
