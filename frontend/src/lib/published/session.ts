/**
 * Loading one session for a page: from what the URL says to a pinned view,
 * and what to do when the pinned generation disappears.
 *
 * These are the decisions a page would otherwise make inside React, where no
 * test in this repository can reach them. They return what happened as a
 * value and do not throw, so a page renders the result and nothing else.
 */

import type { PublishedClient, SessionView } from "./client.ts";
import { isPublishedError, toPublishedFailure } from "./errors.ts";
import type { PublishedFailure } from "./errors.ts";
import { findSession } from "./lookup.ts";
import type { SessionEntry, SessionLookup, SessionRoute } from "./lookup.ts";

export type SessionLoad =
  /** The calendar has no such year, round or session. */
  | { readonly status: "unknown"; readonly missing: "year" | "round" | "session" }
  /** In the calendar, and no pointer: a normal state, not a fault. */
  | { readonly status: "unpublished"; readonly entry: SessionEntry }
  /** `entry` is null when the failure came before the calendar could be read. */
  | { readonly status: "failed"; readonly entry: SessionEntry | null; readonly failure: PublishedFailure }
  /** `recovered` is true once the view has been reopened after its generation went. */
  | {
      readonly status: "ready";
      readonly entry: SessionEntry;
      readonly view: SessionView;
      readonly recovered: boolean;
    };

export type ReadySession = Extract<SessionLoad, { status: "ready" }>;

/** Read the index, find the session the route names, and open a view on it. */
export async function loadSession(client: PublishedClient, route: SessionRoute): Promise<SessionLoad> {
  let lookup: SessionLookup;
  try {
    lookup = findSession(await client.index(), route);
  } catch (error) {
    return { status: "failed", entry: null, failure: toPublishedFailure(error) };
  }
  if (!lookup.found) {
    return { status: "unknown", missing: lookup.missing };
  }
  const { entry } = lookup;
  if (entry.session.session_key === null) {
    return { status: "unpublished", entry };
  }
  return open(client, entry, entry.session.session_key, false);
}

/**
 * Reopen a session whose pinned generation is gone: read the pointer again
 * and pin whatever it names now (rule 1).
 *
 * At most once for each load. A view that was itself a recovery is not
 * reopened, and neither is one whose fresh pointer still names the generation
 * that just answered 404; both would otherwise reload for as long as the
 * files stay missing. The page shows the failure, and its own "try again"
 * starts a new load.
 */
export async function recoverSession(client: PublishedClient, lost: ReadySession): Promise<SessionLoad> {
  const { entry } = lost;
  const { session_key: sessionKey, generation } = lost.view.pointer;
  const stillGone = (message: string): SessionLoad => ({
    status: "failed",
    entry,
    failure: { code: "generation_gone", message, details: { session_key: sessionKey, generation } }
  });

  if (lost.recovered) {
    return stillGone("This session's published data was removed a second time while the page was open.");
  }
  const reopened = await open(client, entry, sessionKey, true);
  if (reopened.status === "ready" && reopened.view.pointer.generation === generation) {
    return stillGone(
      `The pointer of session ${sessionKey} still names generation ${generation.slice(0, 12)}, and files of it are missing.`
    );
  }
  return reopened;
}

/**
 * The same view, which also calls `onGone` the first time one of its reads
 * finds the generation gone. The read still fails with `generation_gone`;
 * this only lets whoever holds the session hear of it without every tab
 * having to pass the news up. Several reads of one tab usually fail together,
 * hence once.
 */
export function notifyWhenGone(view: SessionView, onGone: () => void): SessionView {
  let told = false;
  const watched: SessionView = {
    pointer: view.pointer,
    manifest: view.manifest,
    has: (path) => view.has(path),
    async read<T>(path: string): Promise<T> {
      try {
        return await view.read<T>(path);
      } catch (error) {
        if (!told && isPublishedError(error, "generation_gone")) {
          told = true;
          onGone();
        }
        throw error;
      }
    }
  };
  return Object.freeze(watched);
}

async function open(
  client: PublishedClient,
  entry: SessionEntry,
  sessionKey: number,
  recovered: boolean
): Promise<SessionLoad> {
  try {
    // A recovery exists because the pointer this page read is out of date, so
    // it must not be answered from the same cache entry.
    const view = await client.openSession(sessionKey, { revalidate: recovered });
    return { status: "ready", entry, view, recovered };
  } catch (error) {
    // The index is derived after a pointer is written and is cached on its
    // own, so it can name a session whose pointer is not there. That is the
    // "not published" state like any other missing pointer.
    if (isPublishedError(error, "not_published")) {
      return { status: "unpublished", entry };
    }
    return { status: "failed", entry, failure: toPublishedFailure(error) };
  }
}
