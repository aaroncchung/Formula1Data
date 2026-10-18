import { getPublishedData, isPublishedDataKey } from "./published-data.mjs";
import { sanitizeArtifactPath } from "./session-utils.mjs";

// The read-only Worker of the rewritten data plane (architecture review,
// section 6). It serves `/data/v<N>/...` from R2 exactly as given and does
// nothing else: no queue, no D1, no ingestion routes, no static fallback.
//
// It is deployed beside the old Worker (`index.mjs`, `wrangler.jsonc`) under a
// name of its own, so the old one keeps running untouched until it is removed.
// Its configuration is `wrangler.data.jsonc`.

const SERVICE = "formula-1-data-read";

// Everything here is public, read-only and sent without credentials, and the
// site is also reached through per-branch preview hosts, so any origin may
// read it. The old Worker pinned one origin because it also accepted writes.
const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, OPTIONS",
  // A page may ask for part of an object, or for it only if it changed. A
  // browser asks before sending those headers to another origin, and sends
  // them only if the answer allows them.
  "access-control-allow-headers": "range, if-match, if-none-match, if-modified-since, if-unmodified-since, if-range",
  "access-control-expose-headers": "etag, last-modified, content-length, content-range",
  "access-control-max-age": "86400"
};

export default {
  async fetch(request, env) {
    try {
      return withCors(await route(request, env));
    } catch (error) {
      console.error(
        JSON.stringify({
          message: "data worker request failed",
          method: request.method,
          path: safePathname(request.url),
          error: error instanceof Error ? error.message : String(error)
        })
      );
      return withCors(json({ code: "worker_error", message: "Unexpected Worker error" }, 500));
    }
  }
};

async function route(request, env) {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204 });
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    return json({ code: "method_not_allowed", message: "Only GET and HEAD are supported" }, 405, {
      allow: "GET, HEAD, OPTIONS"
    });
  }

  const { pathname } = new URL(request.url);
  if (pathname === "/health") {
    return json({ status: "ok", service: SERVICE });
  }
  if (!pathname.startsWith("/data/")) {
    return json({ code: "not_found", message: "Route not found" }, 404);
  }

  let key;
  try {
    key = sanitizeArtifactPath(pathname);
  } catch (error) {
    return json(
      {
        code: "invalid_artifact_path",
        message: error instanceof Error ? error.message : "Invalid path"
      },
      400
    );
  }
  // The private source archive, and anything else that is not a published
  // key, does not exist as far as this Worker is concerned.
  const published = isPublishedDataKey(key) ? await getPublishedData(env, key, request) : null;
  return (
    published ||
    json({ code: "artifact_not_found", message: "Artifact was not found", details: { path: key } }, 404)
  );
}

function withCors(response) {
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(CORS_HEADERS)) {
    headers.set(name, value);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

// Everything this Worker says for itself, as opposed to what it reads from the
// bucket, is an answer about now: a 404 for a session that is published a
// minute later must not be remembered by a cache.
function json(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers }
  });
}

function safePathname(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return "<invalid-url>";
  }
}
