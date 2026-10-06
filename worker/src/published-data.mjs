import { serveR2Object } from "./r2-response.mjs";

// The read path for the versioned layout (architecture review, section 6):
//
//   v1/index.json                                    rewritten in place
//   v1/pointers/<session_key>.json                   rewritten in place
//   v1/standings/<year>.json                         rewritten in place
//   v1/generations/<session_key>/<generation_id>/... written once
//
// R2 is the only store for these keys and each one is served exactly as given.
// In particular the Worker never reads a pointer on a request's behalf: the
// page reads the pointer once and then asks for every artifact by its
// generation path, so a view cannot mix two generations (rule 1). There is no
// static fallback either, because a second place to look is a second source of
// truth (AR-03).
//
// Keys must already have been through sanitizeArtifactPath. The `/data/` route
// does that once for every layout, and running it again here would decode the
// path a second time and turn `%252e` into a dot.

// The version is matched by shape rather than listed, so that publishing `v2`
// needs no Worker change (rule 7). Everything else in the bucket, the private
// `archive/` prefix above all, is simply not a published key (rule 4).
const PUBLISHED_KEY = /^v[1-9][0-9]*\/.+/;
const GENERATION_KEY = /^v[1-9][0-9]*\/generations\//;

// A generation is written once under a new name and never changed, so any
// cache may keep it for as long as it likes.
const IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable";

// The index, the pointers and the standings are how a new publication becomes
// visible, so they are held only briefly.
const MUTABLE_CACHE_CONTROL = "public, max-age=30, stale-while-revalidate=120";

export function isPublishedDataKey(key) {
  return typeof key === "string" && PUBLISHED_KEY.test(key);
}

export function publishedDataCacheControl(key) {
  return GENERATION_KEY.test(key) ? IMMUTABLE_CACHE_CONTROL : MUTABLE_CACHE_CONTROL;
}

// Answers a GET or HEAD for a published key. Returns `null` when the key is
// absent from the bucket, or is not a published key at all, and leaves the 404
// to the caller so that it has one shape across the Worker.
export async function getPublishedData(env, key, request = null) {
  if (!isPublishedDataKey(key)) {
    return null;
  }
  const bucket = env.ARTIFACTS_BUCKET;
  if (!bucket?.get || !bucket?.head) {
    // Without the binding every key would look absent, and a site with no
    // sessions is indistinguishable from a misconfigured deployment. A missing
    // store is a fault, not a miss.
    throw new Error("Required ARTIFACTS_BUCKET binding is unavailable");
  }
  return serveR2Object(bucket, key, request, publishedDataCacheControl(key));
}
