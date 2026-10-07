/**
 * The keys of the published layout, relative to the base URL. The reader's
 * copy of f1data/layout.py:
 *
 *   v<F>/index.json                                 the calendar, rewritten in place
 *   v<F>/pointers/<session_key>.json                one per published session, rewritten in place
 *   v<F>/generations/<session_key>/<generation>/    written once, never changed
 *   v<F>/standings/<year>.json                      one per season, rewritten in place
 */

import { FORMAT_VERSION } from "./config.ts";

export const MANIFEST_NAME = "manifest.json";

/**
 * The kinds of session that are published: a race or a sprint
 * (`IN_SCOPE_SESSION_TYPES` in f1data/policy.py). Every file of a generation
 * is written for a session that is raced. A publisher before that rule was
 * kept could give a pointer to a practice or a qualifying session, whose
 * "result" is then an order by laps completed with gaps at a flag.
 */
const SHOWN_SESSION_TYPES: ReadonlySet<string> = new Set(["R", "S"]);

export function isShownSessionType(sessionType: string): boolean {
  return SHOWN_SESSION_TYPES.has(sessionType);
}

const GENERATION_ID = /^[a-f0-9]{64}$/;

/** A generation is named by the SHA-256 of its manifest: 64 lowercase hex characters. */
export function isGenerationId(value: unknown): value is string {
  return typeof value === "string" && GENERATION_ID.test(value);
}

/** F1's session key, which names a session in storage whatever its round is. */
export function isSessionKey(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

/**
 * Whether a manifest may list this path. The path becomes part of a URL under
 * the generation prefix, and a `..` segment would let it name something
 * outside that prefix, which is exactly what a view must not be able to read.
 * The publisher refuses the same paths (`upload_generation`).
 */
export function isArtifactPath(value: unknown): value is string {
  if (typeof value !== "string" || value === "" || value.includes("\\")) {
    return false;
  }
  return value.split("/").every((segment) => segment !== "" && segment !== "." && segment !== "..");
}

export function indexKey(): string {
  return `v${FORMAT_VERSION}/index.json`;
}

export function pointerKey(sessionKey: number): string {
  return `v${FORMAT_VERSION}/pointers/${sessionKey}.json`;
}

export function generationPrefix(sessionKey: number, generation: string): string {
  return `v${FORMAT_VERSION}/generations/${sessionKey}/${generation}/`;
}

export function standingsKey(year: number): string {
  return `v${FORMAT_VERSION}/standings/${year}.json`;
}
