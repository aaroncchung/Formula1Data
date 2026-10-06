// Shared by the tests of the pages that load at runtime. Not a test file: the
// runner only picks up `*.test.mjs`.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { parseIndex } from "../src/lib/published/parse.ts";

// The bucket exactly as the publisher writes one; tests/test_contract_fixture.py
// fails when the publisher stops producing this file byte for byte.
export const PUBLISHED = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/published-v1.json", import.meta.url), "utf8")
);

export const BASE_URL = "https://data.example/data";
export const INDEX_KEY = "v1/index.json";
export const AUSTRIAN_RACE_KEY = 11315;
export const POINTER_KEY = `v1/pointers/${AUSTRIAN_RACE_KEY}.json`;
export const GENERATION = JSON.parse(PUBLISHED[POINTER_KEY]).generation;
export const GENERATION_PREFIX = `v1/generations/${AUSTRIAN_RACE_KEY}/${GENERATION}/`;

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

/** Rewrite one stored JSON object in place. */
export function edit(bucket, key, change) {
  const value = JSON.parse(bucket.stored.get(key));
  change(value);
  bucket.stored.set(key, JSON.stringify(value));
}

const sha256 = (text) => createHash("sha256").update(text).digest("hex");

const generationPrefix = (generation) => `v1/generations/${AUSTRIAN_RACE_KEY}/${generation}/`;

/**
 * Publish the Austrian race again with some files changed, the way
 * `publish_session` does: upload a new generation named by its manifest's
 * SHA-256, then replace the pointer. The old generation stays, as it does in
 * the real bucket. Returns the new generation.
 */
export function republish(bucket, changedFiles) {
  const pointer = JSON.parse(bucket.stored.get(POINTER_KEY));
  const oldPrefix = generationPrefix(pointer.generation);
  const oldManifest = JSON.parse(bucket.stored.get(`${oldPrefix}manifest.json`));
  const files = new Map(oldManifest.files.map((file) => [file.path, bucket.stored.get(`${oldPrefix}${file.path}`)]));
  for (const [path, payload] of Object.entries(changedFiles)) {
    files.set(path, JSON.stringify(payload));
  }
  const manifest = JSON.stringify({
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
    JSON.stringify({
      ...pointer,
      generation,
      manifest: { sha256: generation, size_bytes: Buffer.byteLength(manifest) },
      previous_generation: pointer.generation
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

/** The fixture's own index, parsed the way a page receives it. */
export function fixtureIndex() {
  return parseIndex(JSON.parse(PUBLISHED[INDEX_KEY]));
}

export function session(type, name, start, published = {}) {
  return { type, name, start_time_utc: start, ...published };
}

export function meeting(round, name, date, sessions, extra = {}) {
  return {
    round,
    name,
    official_name: null,
    country: null,
    location: null,
    date,
    format: "conventional",
    sessions,
    ...extra
  };
}

/** An index in the published shape, through the reader's own parser. */
export function indexOf(seasons, unscheduled = []) {
  return parseIndex({ schema_version: 1, format_version: 1, seasons, unscheduled });
}

/**
 * A calendar with everything the pages have to tell apart: a complete and a
 * partial session, sessions that were run and are not published, sessions
 * still to come, a second season, and a published session the calendar has no
 * entry for. "Now" for it is `NOW`.
 */
export const NOW = Date.parse("2026-07-01T00:00:00Z");

export function sampleIndex() {
  return indexOf(
    [
      {
        year: 2025,
        meetings: [
          meeting(24, "Abu Dhabi Grand Prix", "2025-12-07", [
            session("R", "Race", "2025-12-07T13:00:00Z", { session_key: 9001, complete: true })
          ])
        ]
      },
      {
        year: 2026,
        meetings: [
          meeting(
            7,
            "Barcelona Grand Prix",
            "2026-06-14",
            [
              session("Q", "Qualifying", "2026-06-13T14:00:00Z"),
              session("R", "Race", "2026-06-14T13:00:00Z", { session_key: 11300, complete: false })
            ],
            { country: "Spain", location: "Barcelona" }
          ),
          meeting(
            8,
            "Austrian Grand Prix",
            "2026-06-28",
            [
              session("S", "Sprint", "2026-06-27T10:00:00Z", { session_key: 11314, complete: true }),
              session("Q", "Qualifying", "2026-06-27T14:00:00Z"),
              session("R", "Race", "2026-06-28T13:00:00Z", { session_key: 11315, complete: true })
            ],
            { country: "Austria", location: "Spielberg", format: "sprint_qualifying" }
          ),
          meeting(
            9,
            "British Grand Prix",
            "2026-07-05",
            [
              session("Q", "Qualifying", "2026-07-04T15:00:00Z"),
              session("R", "Race", "2026-07-05T14:00:00Z")
            ],
            { country: "United Kingdom", location: "Silverstone" }
          )
        ]
      }
    ],
    [
      {
        session_key: 11200,
        year: 2026,
        type: "R",
        name: "Race",
        meeting_name: "Imola Grand Prix",
        start_time_utc: "2026-05-17T13:00:00Z",
        complete: true
      }
    ]
  );
}
