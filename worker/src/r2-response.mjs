// Turns an R2 object into an HTTP response: conditional requests, ranges and
// HEAD. Nothing here decides which keys are public, where else to look for a
// missing one, or how long a response may be cached. Each caller owns those and
// passes its cache policy in, which keeps this module free of the legacy layout
// so that it can outlive artifact-store.mjs.

// Answers a GET or HEAD for `key` from the bucket. Returns `null` when the
// bucket holds no such object, so the caller decides what a miss means.
export async function serveR2Object(bucket, key, request, cacheControl) {
  const requestHeaders = request?.headers;
  if (request?.method === "HEAD" && bucket?.head) {
    const object = await bucket.head(key);
    return object ? r2ObjectResponse(object, { key, cacheControl, headOnly: true, requestHeaders }) : null;
  }
  if (bucket?.get) {
    const object = await bucket.get(key, r2GetOptions(requestHeaders));
    return object ? r2ObjectResponse(object, { key, cacheControl, requestHeaders }) : null;
  }
  return null;
}

export function r2GetOptions(headers) {
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

export function r2ObjectResponse(object, { key, cacheControl, headOnly = false, requestHeaders = null }) {
  if (!cacheControl) {
    // No policy is a safe default: the layouts served through here range from
    // thirty seconds to immutable. A caller that forgets one should fail in its
    // tests rather than ship responses that caches treat however they like.
    throw new TypeError("r2ObjectResponse requires a cache-control value");
  }

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
  headers.set("cache-control", cacheControl);
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

  // R2 reports the range it returned on every `get`, the whole object included.
  // Only a request that asked for a range gets a 206: the deployed Worker was
  // answering a plain GET of catalog.json with "206, bytes 0-1582/1583", which
  // shared caches do not store the way they store a 200.
  const range = requestHeaders?.has("range") ? object.range : null;
  if (range && Number.isFinite(range.offset) && Number.isFinite(range.length)) {
    const end = range.offset + range.length - 1;
    headers.set("content-range", `bytes ${range.offset}-${end}/${object.size}`);
    headers.set("content-length", String(range.length));
    return new Response(object.body, { status: 206, headers });
  }
  headers.set("content-length", String(object.size));
  return new Response(object.body, { status: 200, headers });
}

export function contentTypeForKey(key) {
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

export function failedPreconditionStatus(object, headers) {
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
