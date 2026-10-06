/**
 * The TypeScript types of the published format, generated from its schema.
 *
 *   npm run types          writes src/lib/published/schema.ts
 *
 * schema/published-v2.schema.json is written by the publisher from its models
 * (`python -m f1data schema`), and is the contract between the two sides. The
 * types are generated from it and committed, so that a page is compiled
 * against what is really published and a change to the format shows up as a
 * type error in whatever reads the part that changed.
 *
 * tests/published-types.test.mjs runs `generatePublishedTypes` and fails when
 * the committed file is not what it returns, which is how a schema that
 * changed without `npm run types` is caught.
 */

import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { compile } from "json-schema-to-typescript";

export const SCHEMA_URL = new URL("../../schema/published-v2.schema.json", import.meta.url);
export const TYPES_URL = new URL("../src/lib/published/schema.ts", import.meta.url);

const BANNER = `/**
 * The published format, as TypeScript types.
 *
 * GENERATED from schema/published-v2.schema.json by \`npm run types\`
 * (scripts/published-types.mjs). Do not edit: change f1data/models.py, write
 * the schema again with \`python -m f1data schema\`, and run \`npm run types\`.
 * tests/published-types.test.mjs fails when this file and the schema differ.
 */`;

/** The schema, parsed. */
export async function readSchema() {
  return JSON.parse(await readFile(SCHEMA_URL, "utf8"));
}

/** The text of the types file for a schema. The same schema always gives the same text. */
export async function generatePublishedTypes(schema) {
  const text = await compile(schema, "PublishedFormat", {
    bannerComment: BANNER,
    // A model that declares its fields closed is closed; nothing is added.
    additionalProperties: false,
    // Every definition, whether or not a path reaches it.
    unreachableDefinitions: true,
    // The schema says which arrays have a length; none is turned into a tuple.
    ignoreMinAndMaxItems: true,
    style: { printWidth: 110, singleQuote: false, trailingComma: "none" }
  });
  return text.replace(/\r\n/g, "\n");
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const text = await generatePublishedTypes(await readSchema());
  await writeFile(TYPES_URL, text);
  console.log(`Wrote ${fileURLToPath(TYPES_URL)} (${text.split("\n").length} lines)`);
}
