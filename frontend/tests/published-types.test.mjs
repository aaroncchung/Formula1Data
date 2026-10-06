import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

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
