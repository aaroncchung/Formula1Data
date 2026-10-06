/**
 * Loading one session for a page: from what the URL says to a pinned view,
 * and what to do when the pinned generation disappears.
 *
 * These are the decisions a page would otherwise make inside React, where no
 * test in this repository can reach them. They return what happened as a
 * value and do not throw, so a page renders the result and nothing else.
 */

import type { PublishedClient, SessionView } from "./client.ts";
import { isPublishedError, safePublished, toPublishedFailure } from "./errors.ts";
import type { PublishedFailure } from "./errors.ts";
import { findSession, findSessionByKey, headingOfEntry, headingOfIdentity, headingOfUnscheduled } from "./lookup.ts";
import type { SessionAddress, SessionEntry, SessionHeading, SessionLookup, SessionRoute } from "./lookup.ts";

export type SessionLoad =
  /** The calendar has no such year, round or session, or nothing is published under the key. */
  | { readonly status: "unknown"; readonly missing: "year" | "round" | "session" | "key" }
  /** In the calendar, and no pointer: a normal state, not a fault. */
  | { readonly status: "unpublished"; readonly entry: SessionEntry; readonly heading: SessionHeading }
  /** `entry` and `heading` are null when the failure came before the index could place the session. */
  | {
      readonly status: "failed";
      readonly entry: SessionEntry | null;
      readonly heading: SessionHeading | null;
      readonly failure: PublishedFailure;
    }
  /**
   * `entry` is null for a session the calendar has no entry for, which only a
   * key can name. `recovered` is true once the view has been reopened after
   * its generation went.
   */
  | {
      readonly status: "ready";
      readonly entry: SessionEntry | null;
      readonly heading: SessionHeading;
      readonly view: SessionView;
      readonly recovered: boolean;
    };

export type ReadySession = Extract<SessionLoad, { status: "ready" }>;

/** What the index said about a session before its pointer was read. */
type Placed = { readonly entry: SessionEntry | null; readonly heading: SessionHeading | null };

/** Load the session an address names, whichever way it names it. */
export function loadAddress(client: PublishedClient, address: SessionAddress): Promise<SessionLoad> {
  return address.kind === "key" ? loadSessionByKey(client, address.sessionKey) : loadSession(client, address.route);
}

/** Read the index, find the session the route names, and open a view on it. */
export async function loadSession(client: PublishedClient, route: SessionRoute): Promise<SessionLoad> {
  let lookup: SessionLookup;
  try {
    lookup = findSession(await client.index(), route);
  } catch (error) {
    return { status: "failed", entry: null, heading: null, failure: toPublishedFailure(error) };
  }
  if (!lookup.found) {
    return { status: "unknown", missing: lookup.missing };
  }
  const { entry } = lookup;
  const heading = headingOfEntry(entry);
  if (entry.session.session_key === null) {
    return { status: "unpublished", entry, heading };
  }
  return open(client, { entry, heading }, entry.session.session_key, false);
}

/**
 * Open a view on the session with this key.
 *
 * The pointer is what says a session is published and who it is, so it is
 * read whatever the index says, and at the same time as the index. The index
 * only adds where the calendar puts the session today. A key therefore still
 * opens a session the calendar has no entry for, one published a moment ago
 * that the index does not list yet, and any session while the index cannot be
 * read; the heading then has no round.
 */
export async function loadSessionByKey(client: PublishedClient, sessionKey: number): Promise<SessionLoad> {
  const [index, opened] = await Promise.all([
    safePublished(() => client.index()),
    safePublished(() => client.openSession(sessionKey))
  ]);
  const place = index.ok ? findSessionByKey(index.data, sessionKey) : null;
  const placed: Placed =
    place === null
      ? { entry: null, heading: null }
      : place.kind === "calendar"
        ? { entry: place.entry, heading: headingOfEntry(place.entry) }
        : { entry: null, heading: headingOfUnscheduled(place.session) };
  return opened.ok ? ready(placed, opened.data, false) : notOpened(placed, opened.error);
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
  const { entry, heading } = lost;
  const { session_key: sessionKey, generation } = lost.view.pointer;
  const stillGone = (message: string): SessionLoad => ({
    status: "failed",
    entry,
    heading,
    failure: { code: "generation_gone", message, details: { session_key: sessionKey, generation } }
  });

  if (lost.recovered) {
    return stillGone("This session's published data was removed a second time while the page was open.");
  }
  const reopened = await open(client, { entry, heading }, sessionKey, true);
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
  placed: Placed,
  sessionKey: number,
  recovered: boolean
): Promise<SessionLoad> {
  // A recovery exists because the pointer this page read is out of date, so
  // it must not be answered from the same cache entry.
  const opened = await safePublished(() => client.openSession(sessionKey, { revalidate: recovered }));
  return opened.ok ? ready(placed, opened.data, recovered) : notOpened(placed, opened.error);
}

function ready(placed: Placed, view: SessionView, recovered: boolean): SessionLoad {
  return {
    status: "ready",
    entry: placed.entry,
    // The index had nothing to say, so the session introduces itself.
    heading: placed.heading ?? headingOfIdentity(view.pointer.identity),
    view,
    recovered
  };
}

function notOpened(placed: Placed, failure: PublishedFailure): SessionLoad {
  if (failure.code !== "not_published") {
    return { status: "failed", entry: placed.entry, heading: placed.heading, failure };
  }
  // The index is derived after a pointer is written and is cached on its
  // own, so it can name a session whose pointer is not there. For a session
  // in the calendar that is the "not published" state like any other missing
  // pointer. Outside the calendar there is nothing left that the key names.
  return placed.entry
    ? { status: "unpublished", entry: placed.entry, heading: placed.heading ?? headingOfEntry(placed.entry) }
    : { status: "unknown", missing: "key" };
}
