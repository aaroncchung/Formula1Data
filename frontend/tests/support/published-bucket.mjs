/**
 * A stand-in for the published bucket behind the read-only Worker, for the
 * tests of the reader. Shared by the test files that read through it.
 */

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { createPublishedClient } from "../../src/lib/published/client.ts";
import { safePublished } from "../../src/lib/published/errors.ts";

// The bucket exactly as the publisher writes one. tests/test_contract_fixture.py
// fails when the publisher stops producing this file byte for byte, and the
// Worker is tested against it too (worker/tests/data-worker.test.mjs), so the
// reader is tested against what is really published and served.
export const PUBLISHED = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/published-v2.json", import.meta.url), "utf8")
);

export const BASE_URL = "https://data.example/data";
export const SESSION_KEY = 11315;
export const INDEX_KEY = "v2/index.json";
export const POINTER_KEY = `v2/pointers/${SESSION_KEY}.json`;
export const AUSTRIAN_RACE = { year: 2026, round: 8, sessionType: "R" };

export const generationPrefix = (generation) => `v2/generations/${SESSION_KEY}/${generation}/`;
export const sha256 = (text) => createHash("sha256").update(text).digest("hex");

/** Minified, key-sorted JSON with a trailing newline: the publisher's `dump_json`. */
export function dumpJson(value) {
  const sorted = (item) =>
    Array.isArray(item)
      ? item.map(sorted)
      : item && typeof item === "object"
        ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, sorted(item[key])]))
        : item;
  return `${JSON.stringify(sorted(value))}\n`;
}

/**
 * A stand-in for the Worker in front of a bucket. It serves a key exactly as
 * given, answers 404 in the Worker's own shape for a key it does not hold, and
 * records every request. `fault` lets one test break chosen keys: return an
 * Error to fail the request, or a Response to answer with it.
 */
export function bucketOf(objects = PUBLISHED) {
  const bucket = {
    stored: new Map(Object.entries(objects)),
    requests: [],
    fault: () => undefined,
    keys: () => bucket.requests.map((request) => request.key),
    count: (key) => bucket.requests.filter((request) => request.key === key).length,
    fetch: async (url, init) => {
      assert.ok(url.startsWith(`${BASE_URL}/`), `a request left the base URL: ${url}`);
      const key = decodeURIComponent(url.slice(BASE_URL.length + 1));
      bucket.requests.push({ key, cache: init?.cache });
      const broken = bucket.fault(key);
      if (broken instanceof Error) {
        throw broken;
      }
      if (broken) {
        return broken;
      }
      const text = bucket.stored.get(key);
      if (text === undefined) {
        return Response.json(
          { code: "artifact_not_found", message: "Artifact was not found", details: { path: key } },
          { status: 404 }
        );
      }
      return new Response(text, { status: 200 });
    }
  };
  return bucket;
}

export function clientOf(bucket, options = {}) {
  return createPublishedClient({ baseUrl: BASE_URL, fetch: bucket.fetch, ...options });
}

export function readStored(bucket, key) {
  return JSON.parse(bucket.stored.get(key));
}

/** Rewrite one stored JSON object in place. */
export function edit(bucket, key, change) {
  const value = readStored(bucket, key);
  change(value);
  bucket.stored.set(key, dumpJson(value));
}

/**
 * Publish the session again with some files changed, the way `publish_session`
 * does: upload a new generation named by its manifest's SHA-256, then replace
 * the pointer. The old generation stays, as it does in the real bucket.
 * `without` names files the new generation leaves out.
 */
export function republish(bucket, changedFiles, { without = [] } = {}) {
  const pointer = readStored(bucket, POINTER_KEY);
  const oldPrefix = generationPrefix(pointer.generation);
  const oldManifest = readStored(bucket, `${oldPrefix}manifest.json`);
  const files = new Map(oldManifest.files.map((file) => [file.path, bucket.stored.get(`${oldPrefix}${file.path}`)]));
  for (const [path, payload] of Object.entries(changedFiles)) {
    files.set(path, dumpJson(payload));
  }
  for (const path of without) {
    files.delete(path);
  }
  const manifest = dumpJson({
    ...oldManifest,
    files: [...files.keys()].sort().map((path) => ({
      path,
      size_bytes: Buffer.byteLength(files.get(path)),
      sha256: sha256(files.get(path))
    }))
  });
  const generation = sha256(manifest);
  for (const [path, text] of files) {
    bucket.stored.set(`${generationPrefix(generation)}${path}`, text);
  }
  bucket.stored.set(`${generationPrefix(generation)}manifest.json`, manifest);
  bucket.stored.set(
    POINTER_KEY,
    dumpJson({
      ...pointer,
      generation,
      manifest: { sha256: generation, size_bytes: Buffer.byteLength(manifest) },
      previous_generation: pointer.generation,
      published_at: "2026-10-06T09:00:00Z"
    })
  );
  return generation;
}

/** Remove every file of a generation except those named, as pruning would. */
export function removeGeneration(bucket, generation, { keep = [] } = {}) {
  const prefix = generationPrefix(generation);
  for (const key of [...bucket.stored.keys()]) {
    if (key.startsWith(prefix) && !keep.includes(key.slice(prefix.length))) {
      bucket.stored.delete(key);
    }
  }
}

/** The failure a promise rejects with, as a page would receive it. */
export async function failureOf(promise) {
  const result = await safePublished(() => promise);
  assert.equal(result.ok, false, "expected the read to fail");
  return result.error;
}

// The generation the fixture's pointer names, and a changed classification to
// publish over it.
export const FIRST_GENERATION = JSON.parse(PUBLISHED[POINTER_KEY]).generation;
export const reversedResults = () => JSON.parse(PUBLISHED[`${generationPrefix(FIRST_GENERATION)}results.json`]).reverse();
