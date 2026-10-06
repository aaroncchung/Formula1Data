/**
 * How the published-data reader reports a failure.
 *
 * The model is the one in static-api-core.ts: a reader throws a typed error
 * that carries `{code, message, details}`, and `safePublished` turns a loader
 * that throws into a discriminated result, as `safeApi` does. The code is a
 * closed set here because the page has to treat the cases differently. "Not
 * published" is a normal state, "the pointer is invalid" is a fault, and "the
 * generation is gone" asks for a reload; collapsing any two of them shows the
 * user the wrong thing.
 */

export type PublishedErrorCode =
  /** The build was given no base URL. */
  | "not_configured"
  /** A network failure, a timeout, or any error status other than 404. Says nothing about what exists. */
  | "unavailable"
  /** The index is absent. */
  | "index_missing"
  /** The index exists and cannot be trusted. */
  | "invalid_index"
  /** The session's pointer is absent, which is what "not published" means. */
  | "not_published"
  /** The pointer exists and cannot be trusted. Never shown as "not published". */
  | "invalid_pointer"
  /** The manifest of the pinned generation cannot be trusted. */
  | "invalid_manifest"
  /** The data is in a format this build does not read. */
  | "format_mismatch"
  /** A path under the pinned generation answered 404: the generation was removed. */
  | "generation_gone"
  /** A path the manifest does not list was asked for. No request is made. */
  | "not_in_manifest"
  /** An artifact arrived and is not what its name promises. */
  | "invalid_artifact"
  /** A season's standings exist and cannot be trusted. Absent standings are not an error. */
  | "invalid_standings"
  /** Something that is not the reader's own error; a bug rather than a state of the data. */
  | "unknown";

export type PublishedFailure = {
  readonly code: PublishedErrorCode;
  readonly message: string;
  readonly details: Readonly<Record<string, unknown>>;
};

export type PublishedResult<T> =
  | { readonly ok: true; readonly data: T }
  | { readonly ok: false; readonly error: PublishedFailure };

export class PublishedDataError extends Error {
  // Declared as fields and assigned below, not as constructor parameter
  // properties: the test runner strips types and cannot run syntax that needs
  // compiling.
  readonly code: PublishedErrorCode;
  readonly details: Readonly<Record<string, unknown>>;

  constructor(code: PublishedErrorCode, message: string, details: Readonly<Record<string, unknown>> = {}) {
    super(message);
    this.name = "PublishedDataError";
    this.code = code;
    this.details = details;
  }
}

/** Whatever was thrown, as the payload a page renders. */
export function toPublishedFailure(error: unknown): PublishedFailure {
  if (error instanceof PublishedDataError) {
    return { code: error.code, message: error.message, details: error.details };
  }
  return {
    code: "unknown",
    message: error instanceof Error ? error.message : "Unknown error",
    details: {}
  };
}

/** Run a loader and return its failure instead of throwing it, as `safeApi` does. */
export async function safePublished<T>(loader: () => Promise<T>): Promise<PublishedResult<T>> {
  try {
    return { ok: true, data: await loader() };
  } catch (error) {
    return { ok: false, error: toPublishedFailure(error) };
  }
}

export function isPublishedError(error: unknown, code: PublishedErrorCode): error is PublishedDataError {
  return error instanceof PublishedDataError && error.code === code;
}
