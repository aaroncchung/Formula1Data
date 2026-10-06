/**
 * Where published data is read from, and which format this build reads.
 *
 * Pages and data deploy separately once pages load at runtime, so the two can
 * disagree (docs/architecture-review-findings.md, section 6, rule 7). The
 * format version is therefore part of every path and is checked again in the
 * pointer and in the manifest of the generation a view pinned.
 */

// The artifact format: file names, shapes and units. Mirrors FORMAT_VERSION in
// f1data/layout.py. A new format is published under a new prefix before the
// frontend that reads it is deployed, so this build never has to read two.
export const FORMAT_VERSION = 2;

// The versions of the two envelopes the reader parses before it reaches any
// artifact. Mirror POINTER_SCHEMA_VERSION and INDEX_SCHEMA_VERSION in
// f1data/publish.py.
export const POINTER_SCHEMA_VERSION = 1;
export const INDEX_SCHEMA_VERSION = 1;

// The version of a season's standings. Mirrors STANDINGS_SCHEMA_VERSION in
// f1data/standings.py.
export const STANDINGS_SCHEMA_VERSION = 1;

/**
 * The URL the versioned layout hangs off, for example `https://host/data`.
 * Empty when the build was not given one; the client reports that as its own
 * failure instead of requesting paths on whatever origin served the page.
 */
export function publishedDataBaseUrl(): string {
  // Spelled out in full because Next.js replaces this exact expression with
  // the value at build time; any indirection would leave it undefined in the
  // browser.
  return process.env.NEXT_PUBLIC_PUBLISHED_DATA_BASE_URL ?? "";
}
