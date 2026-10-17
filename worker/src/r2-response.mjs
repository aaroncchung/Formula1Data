// Turns an R2 object into an HTTP response: conditional requests, ranges and
// HEAD. Nothing here decides which keys are public, where else to look for a
// missing one, or how long a response may be cached. Each caller owns those and
// passes its cache policy in, which keeps this module free of the legacy layout
// so that it can outlive artifact-store.mjs.

// A precondition that failed is an answer about one request's headers, not
// about the object, so no cache may keep it. Without this a 412 for a
// generation path went out marked immutable for a year.
const FAILED_PRECONDITION_CACHE_CONTROL = "no-store";

// A range that asks for no bytes of the object is answered for this request
// alone, like a failed precondition.
const UNSATISFIABLE_RANGE_CACHE_CONTROL = "no-store";

// Answers a GET or HEAD for `key` from the bucket. Returns `null` when the
// bucket holds no such object, so the caller decides what a miss means.
export async function serveR2Object(bucket, key, request, cacheControl) {
  const requestHeaders = request?.headers;
  if (request?.method === "HEAD" && bucket?.head) {
    const object = await bucket.head(key);
    return object ? r2ObjectResponse(object, { key, cacheControl, headOnly: true, requestHeaders }) : null;
  }
  if (bucket?.get) {
    // R2 is handed a range only as this module reads one. Given the request's
    // own header, R2 sent the whole object for `bytes=abc`, which went out as
    // a 206, and threw for a range past the end, which went out as a 500.
    const asked = parseByteRange(requestHeaders?.get("range"));
    if (asked?.suffix === 0) {
      return unsatisfiedRange(bucket, key, requestHeaders, asked, cacheControl, null);
    }
    let rangeHeaders = asked ? new Headers({ range: byteRangeHeader(asked) }) : null;
    let object;
    try {
      object = await bucket.get(key, r2GetOptions(requestHeaders, rangeHeaders));
    } catch (error) {
      if (!rangeHeaders) {
        throw error;
      }
      return unsatisfiedRange(bucket, key, requestHeaders, asked, cacheControl, error);
    }
    if (object?.body && rangeHeaders && !ifRangeHolds(object, requestHeaders)) {
      // Not the version the client holds part of: send all of the one there is.
      await object.body.cancel?.();
      rangeHeaders = null;
      object = await bucket.get(key, r2GetOptions(requestHeaders, null));
    }
    return object ? r2ObjectResponse(object, { key, cacheControl, requestHeaders, rangeHeaders }) : null;
  }
  return null;
}

// The one range of a `Range` header, or null for a header to ignore. R2
// serves a single range, and RFC 9110 lets a server ignore a header it cannot
// or will not use, several ranges and a malformed one alike, and send the
// whole object. `{offset, last}` is `bytes=offset-last`, with `last` null for
// `bytes=offset-`; `{suffix}` is `bytes=-suffix`, the last `suffix` bytes.
export function parseByteRange(value) {
  const match = /^bytes=([0-9]*)-([0-9]*)$/i.exec(String(value ?? "").trim());
  if (!match || (match[1] === "" && match[2] === "")) {
    return null;
  }
  const [, first, last] = match;
  if (first === "") {
    return { suffix: Number(last) };
  }
  if (last !== "" && Number(last) < Number(first)) {
    return null;
  }
  return { offset: Number(first), last: last === "" ? null : Number(last) };
}

function byteRangeHeader(range) {
  return "suffix" in range ? `bytes=-${range.suffix}` : `bytes=${range.offset}-${range.last ?? ""}`;
}

// Whether a range has any byte of an object of this size in it. A range that
// runs past the end is cut at the end, so only where it starts matters.
function rangeSatisfiable(range, size) {
  return "suffix" in range ? range.suffix > 0 : range.offset < size;
}

// R2 threw while reading a range, or the range asks for no bytes at all. A
// look at the object says which it is: absent, a range to answer with 416 and
// the object's size, or a fault to pass on. Preconditions come before a range
// (RFC 9110), and an `If-Range` that does not hold means the range is ignored
// and the whole object sent.
async function unsatisfiedRange(bucket, key, requestHeaders, range, cacheControl, error) {
  const object = await bucket.head(key);
  if (!object) {
    return null;
  }
  if (rangeSatisfiable(range, object.size)) {
    throw error ?? new Error(`R2 could not read ${byteRangeHeader(range)} of ${key}`);
  }
  if (!ifRangeHolds(object, requestHeaders)) {
    const whole = await bucket.get(key, r2GetOptions(requestHeaders, null));
    return whole ? r2ObjectResponse(whole, { key, cacheControl, requestHeaders, rangeHeaders: null }) : null;
  }
  return r2ObjectResponse(object, { key, cacheControl, requestHeaders, unsatisfiableRange: true });
}

// `If-Range` makes a range request conditional: the range is honoured only if
// the object is still the version the client holds part of. Otherwise the whole
// current object is sent, so a resumed download cannot stitch two versions
// together. That matters for the pointers and the index, which change in place.
//
// The validator is compared with the object the range was read from, not with
// a look at the object beforehand: a publication between the look and the read
// would hand the client part of a version it never asked about.
function ifRangeHolds(object, headers) {
  const validator = headers?.get("if-range");
  if (!validator) {
    return true;
  }
  if (validator.startsWith('"') || validator.startsWith("W/")) {
    return strongEtagMatch(validator, object.httpEtag);
  }
  const held = Date.parse(validator);
  return Number.isFinite(held) && held === lastModifiedMs(object);
}

function r2GetOptions(headers, rangeHeaders) {
  if (!headers) {
    return undefined;
  }
  const options = {};
  if (rangeHeaders) {
    options.range = rangeHeaders;
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

export function r2ObjectResponse(
  object,
  {
    key,
    cacheControl,
    headOnly = false,
    requestHeaders = null,
    rangeHeaders = requestHeaders,
    unsatisfiableRange = false
  }
) {
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
    return conditionResponse(preconditionStatus, headers);
  }

  if (unsatisfiableRange) {
    headers.set("content-range", `bytes */${object.size}`);
    headers.set("cache-control", UNSATISFIABLE_RANGE_CACHE_CONTROL);
    return new Response(null, { status: 416, headers });
  }

  if (headOnly) {
    headers.set("content-length", String(object.size));
    return new Response(null, { status: 200, headers });
  }

  if (!object.body) {
    // R2 judged the request's conditions itself and withheld the body.
    const failed = requestHeaders?.has("if-match") || requestHeaders?.has("if-unmodified-since");
    return conditionResponse(failed ? 412 : 304, headers);
  }

  // R2 reports the range it returned on every `get`, the whole object included.
  // Only a request that asked for a range gets a 206: the deployed Worker was
  // answering a plain GET of catalog.json with "206, bytes 0-1582/1583", which
  // shared caches do not store the way they store a 200.
  const range = rangeHeaders?.has("range") ? returnedRange(object) : null;
  if (range) {
    const end = range.offset + range.length - 1;
    headers.set("content-range", `bytes ${range.offset}-${end}/${object.size}`);
    headers.set("content-length", String(range.length));
    return new Response(object.body, { status: 206, headers });
  }
  headers.set("content-length", String(object.size));
  return new Response(object.body, { status: 200, headers });
}

// The bytes R2 says it returned, as an offset and a length, or null when it
// says nothing. An R2 range may also be a suffix, or an offset or a length
// alone, and each is turned into the bytes it covers.
function returnedRange(object) {
  const { range, size } = object;
  if (!range || !Number.isFinite(size)) {
    return null;
  }
  if (Number.isFinite(range.suffix)) {
    const length = Math.min(range.suffix, size);
    return { offset: size - length, length };
  }
  if (!Number.isFinite(range.offset) && !Number.isFinite(range.length)) {
    return null;
  }
  const offset = Number.isFinite(range.offset) ? range.offset : 0;
  return { offset, length: Number.isFinite(range.length) ? range.length : size - offset };
}

function conditionResponse(status, headers) {
  headers.delete("content-length");
  if (status === 412) {
    headers.set("cache-control", FAILED_PRECONDITION_CACHE_CONTROL);
  }
  return new Response(null, { status, headers });
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

// The order and the comparisons are RFC 9110's: `If-Match` compares strongly
// and takes precedence over `If-Unmodified-Since`; `If-None-Match` compares
// weakly and takes precedence over `If-Modified-Since`.
export function failedPreconditionStatus(object, headers) {
  if (!headers) {
    return null;
  }
  const etag = object.httpEtag;
  const modified = lastModifiedMs(object);

  const ifMatch = headers.get("if-match");
  if (ifMatch && etag && !etagList(ifMatch).some((value) => value === "*" || strongEtagMatch(value, etag))) {
    return 412;
  }
  const ifUnmodifiedSince = Date.parse(headers.get("if-unmodified-since") || "");
  if (!ifMatch && modified !== null && Number.isFinite(ifUnmodifiedSince) && modified > ifUnmodifiedSince) {
    return 412;
  }
  const ifNoneMatch = headers.get("if-none-match");
  if (ifNoneMatch && etag) {
    return etagList(ifNoneMatch).some((value) => value === "*" || weakEtagMatch(value, etag)) ? 304 : null;
  }
  const ifModifiedSince = Date.parse(headers.get("if-modified-since") || "");
  if (modified !== null && Number.isFinite(ifModifiedSince) && modified <= ifModifiedSince) {
    return 304;
  }
  return null;
}

// An HTTP date has no fraction of a second, and `Last-Modified` is sent that
// way. Comparing a client's copy of it with the upload time to the millisecond
// would call an object modified since the very date this Worker gave for it.
function lastModifiedMs(object) {
  return object.uploaded instanceof Date ? Math.floor(object.uploaded.getTime() / 1000) * 1000 : null;
}

function etagList(headerValue) {
  return String(headerValue)
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function strongEtagMatch(candidate, etag) {
  return Boolean(etag) && !candidate.startsWith("W/") && !String(etag).startsWith("W/") && candidate === etag;
}

function weakEtagMatch(candidate, etag) {
  return candidate.replace(/^W\//, "") === String(etag).replace(/^W\//, "");
}
