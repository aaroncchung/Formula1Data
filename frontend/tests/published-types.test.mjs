import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { ARTIFACTS, tabArtifacts } from "../src/lib/published/artifacts.ts";
import { SESSION_TABS } from "../src/lib/published/tabs.ts";

import { generatePublishedTypes, readSchema, TYPES_URL } from "../scripts/published-types.mjs";

// src/lib/published/schema.ts is generated from schema/published-v2.schema.json
// and committed. These tests are what keeps the two together: the publisher
// changes the schema, and until `npm run types` is run again the first one
// fails.

const committedTypes = async () => (await readFile(TYPES_URL, "utf8")).replace(/\r\n/g, "\n");

test("the committed types are what the generator makes of the schema", async () => {
  const generated = await generatePublishedTypes(await readSchema());

  assert.equal(
    await committedTypes(),
    generated,
    "src/lib/published/schema.ts is not what schema/published-v2.schema.json generates. Run `npm run types` and commit the result."
  );
});

test("a change to the schema changes the types, so drift cannot pass unnoticed", async () => {
  const committed = await committedTypes();

  // A field is added to one artifact, as a format change would add it.
  const added = await readSchema();
  added.$defs.SessionSummary.properties.sunset_utc = { type: "string" };
  assert.notEqual(await generatePublishedTypes(added), committed);

  // A field that could not be null now can.
  const loosened = await readSchema();
  loosened.$defs.Result.properties.driver_code = { anyOf: [{ type: "string" }, { type: "null" }] };
  assert.notEqual(await generatePublishedTypes(loosened), committed);

  // A file is no longer published.
  const removed = await readSchema();
  delete removed.properties["generations/{session_key}/{generation}/corners.json"];
  assert.notEqual(await generatePublishedTypes(removed), committed);
});

test("every path the schema publishes has a type, under the path it is published at", async () => {
  const schema = await readSchema();
  const committed = await committedTypes();

  const paths = Object.keys(schema.properties);
  assert.ok(paths.length >= 27, `the schema lists ${paths.length} paths`);
  for (const path of paths) {
    const definition = schema.properties[path].$ref.replace("#/$defs/", "");
    assert.ok(committed.includes(`"${path}": ${definition};`), `${path} is not typed as ${definition}`);
  }
});

// The types of the files a page reads are looked up from their paths
// (`GenerationFiles`), so a path the schema lacks does not compile. This is
// the same check at run time, and the other half of it: which files the
// format publishes that no page reads, so that leaving one unread is a
// decision somebody made and not a file nobody noticed.
test("every file a page reads is one the schema publishes, and the unread ones are known", async () => {
  const schema = await readSchema();
  const prefix = "generations/{session_key}/{generation}/";
  const published = Object.keys(schema.properties)
    .filter((path) => path.startsWith(prefix))
    .map((path) => path.slice(prefix.length));

  const read = new Set(Object.values(ARTIFACTS).map((file) => file.path));
  for (const tab of SESSION_TABS) {
    for (const path of [...tabArtifacts(tab.id).required, ...tabArtifacts(tab.id).optional]) {
      read.add(path);
    }
  }
  for (const path of read) {
    assert.ok(published.includes(path), `a page reads ${path}, which the schema does not publish`);
  }

  assert.deepEqual(published.filter((path) => !read.has(path)).sort(), [
    // The figures behind a session's coverage verdict; the pointer carries the verdict and its shortfalls.
    "coverage.json",
    // Read by the client, to pin the generation, and not as a page's file.
    "manifest.json",
    // One path for every driver's file; the telemetry index names the files (telemetry.ts).
    "telemetry/{driver_code}.json"
  ]);
});
