/**
 * The reader of the published layout.
 *
 * A session is read through a view. Opening one reads the session's pointer
 * once, pins the generation the pointer names, and from then on builds every
 * request from that generation's path (docs/architecture-review-findings.md,
 * section 6, rule 1). The Worker serves keys as given and resolves nothing, so
 * the pinning has to happen here: a reader that looked the pointer up again
 * for each artifact would, across a publication, show results from one
 * generation next to lap times from the next.
 *
 * Nothing is cached here. Generation paths are immutable and the pointer and
 * index are short-lived, and the browser's HTTP cache already holds each for
 * as long as the Worker says it may.
 */

import { PublishedDataError } from "./errors.ts";
import type { PublishedErrorCode } from "./errors.ts";
import { MANIFEST_NAME, generationPrefix, indexKey, isSessionKey, pointerKey } from "./layout.ts";
import { parseIndex, parseManifest, parsePointer } from "./parse.ts";
import type { Manifest, Pointer, PublishedIndex } from "./types.ts";

const DEFAULT_TIMEOUT_MS = 30_000;

/** The part of `fetch` the reader uses. The global `fetch` fits, and so does a test's stand-in. */
export type PublishedFetch = (url: string, init?: RequestInit) => Promise<Pick<Response, "status" | "text">>;

export type PublishedClientOptions = {
  /** What the layout hangs off, for example `https://host/data`. */
  readonly baseUrl: string;
  /** Injected so that tests need no network. */
  readonly fetch: PublishedFetch;
  /** How long one request may take before it counts as unavailable. */
  readonly timeoutMs?: number;
};

export type OpenSessionOptions = {
  /**
   * Have the HTTP cache check the pointer with the server before using its
   * copy. The pointer may be cached for 30 seconds and served stale for two
   * minutes more, which is fine for a first load and wrong for a reload that
   * was caused by the cached pointer's generation having gone.
   */
  readonly revalidate?: boolean;
};

/** One session, pinned to one generation for as long as the view is held. */
export type SessionView = {
  readonly pointer: Pointer;
  readonly manifest: Manifest;
  /** Whether the pinned generation holds this file. Makes no request. */
  has(path: string): boolean;
  /**
   * Read one file of the pinned generation. `T` is taken on trust: the
   * manifest's format version is what says the artifacts have the shapes this
   * build was written for (rule 7).
   */
  read<T>(path: string): Promise<T>;
};

export type PublishedClient = {
  index(): Promise<PublishedIndex>;
  openSession(sessionKey: number, options?: OpenSessionOptions): Promise<SessionView>;
};

type Answer =
  | { readonly found: true; readonly url: string; readonly text: string }
  | { readonly found: false; readonly url: string };

export function createPublishedClient(options: PublishedClientOptions): PublishedClient {
  // Held as a plain function, not called as `options.fetch(...)`: a browser's
  // `fetch` throws when its receiver is anything but the global object.
  const { fetch: request, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const base = options.baseUrl.replace(/\/+$/, "");

  /**
   * One GET. Only a 404 means "absent"; a network failure, a timeout or any
   * other status says nothing about what exists, and is reported as
   * unavailable so that an outage is never shown as an unpublished session.
   */
  async function get(key: string, init: RequestInit = {}): Promise<Answer> {
    if (!base) {
      throw new PublishedDataError("not_configured", "No base URL for published data is configured.");
    }
    // Encoded segment by segment so that nothing in a key can be read by the
    // URL parser as a query, a fragment or a parent directory.
    const url = `${base}/${key.split("/").map(encodeURIComponent).join("/")}`;
    let response: Awaited<ReturnType<PublishedFetch>>;
    try {
      response = await request(url, { ...init, signal: AbortSignal.timeout(timeoutMs) });
    } catch (error) {
      throw unreachable(url, error);
    }
    if (response.status === 404) {
      return { found: false, url };
    }
    if (response.status < 200 || response.status > 299) {
      throw new PublishedDataError("unavailable", `${url} answered ${response.status}.`, {
        url,
        status: response.status
      });
    }
    try {
      return { found: true, url, text: await response.text() };
    } catch (error) {
      throw unreachable(url, error);
    }
  }

  async function index(): Promise<PublishedIndex> {
    const answer = await get(indexKey());
    if (!answer.found) {
      throw new PublishedDataError("index_missing", `There is no index of published data at ${answer.url}.`, {
        url: answer.url
      });
    }
    return parseIndex(decode(answer, "invalid_index", "The index of published data"));
  }

  async function openSession(sessionKey: number, { revalidate = false }: OpenSessionOptions = {}): Promise<SessionView> {
    if (!isSessionKey(sessionKey)) {
      throw new RangeError(`Not a session key: ${String(sessionKey)}`);
    }

    // The one pointer read of this view (rule 1). A 404 is the "not
    // published" state; anything else that is wrong with the pointer is a
    // fault raised by `decode` or `parsePointer`, under a different code.
    const pointerAnswer = await get(pointerKey(sessionKey), revalidate ? { cache: "no-cache" } : {});
    if (!pointerAnswer.found) {
      throw new PublishedDataError("not_published", `Session ${sessionKey} has no pointer, so it is not published.`, {
        session_key: sessionKey,
        url: pointerAnswer.url
      });
    }
    const pointer = parsePointer(
      decode(pointerAnswer, "invalid_pointer", `The pointer of session ${sessionKey}`),
      sessionKey
    );

    // Every later request of this view is this string plus a path from the
    // manifest. The view keeps no way to reach the pointer again, so it cannot
    // follow a later publication and mix two generations.
    const prefix = generationPrefix(pointer.session_key, pointer.generation);

    const manifestAnswer = await get(`${prefix}${MANIFEST_NAME}`);
    if (!manifestAnswer.found) {
      throw generationGone(pointer, MANIFEST_NAME, manifestAnswer.url);
    }
    const manifest = parseManifest(
      decode(manifestAnswer, "invalid_manifest", `The manifest of session ${sessionKey}`),
      pointer.session_key
    );
    const listed = new Set(manifest.files.map((file) => file.path));

    const view: SessionView = {
      pointer,
      manifest,
      has: (path) => listed.has(path),
      async read<T>(path: string): Promise<T> {
        // Checked before the request, so a path the generation does not hold
        // costs nothing and cannot be mistaken for a generation that is gone.
        if (!listed.has(path)) {
          throw new PublishedDataError(
            "not_in_manifest",
            `${path} is not one of the files of this session's published generation.`,
            { session_key: pointer.session_key, generation: pointer.generation, path }
          );
        }
        const answer = await get(`${prefix}${path}`);
        if (!answer.found) {
          // The manifest is written last, so a generation that has one was
          // whole. A listed file that is absent means the generation was
          // removed after this view pinned it (rule 1).
          throw generationGone(pointer, path, answer.url);
        }
        return decode(answer, "invalid_artifact", path) as T;
      }
    };
    return Object.freeze(view);
  }

  return Object.freeze({ index, openSession });
}

function decode(
  answer: { readonly url: string; readonly text: string },
  code: PublishedErrorCode,
  subject: string
): unknown {
  try {
    const value: unknown = JSON.parse(answer.text);
    return value;
  } catch {
    throw new PublishedDataError(code, `${subject} is not JSON.`, { url: answer.url });
  }
}

function unreachable(url: string, cause: unknown): PublishedDataError {
  const reason = cause instanceof Error ? cause.message : String(cause);
  return new PublishedDataError("unavailable", `${url} could not be read: ${reason}`, { url, reason });
}

function generationGone(pointer: Pointer, path: string, url: string): PublishedDataError {
  return new PublishedDataError(
    "generation_gone",
    `Generation ${pointer.generation.slice(0, 12)} of session ${pointer.session_key} is no longer there: ${path} answered 404.`,
    { session_key: pointer.session_key, generation: pointer.generation, path, url }
  );
}
