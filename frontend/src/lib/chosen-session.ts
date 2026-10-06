/**
 * Loading the one session a summary page shows: the session the reader chose
 * by its key, or the most recent published one when they chose none.
 *
 * The page reads the calendar, opens a view on the session and reads every
 * artifact through that view, so everything on screen comes from one
 * generation (rule 1). A session is found by its key alone. Year, round and
 * names are read from the calendar afterwards, for display, and are never
 * what decides which session is opened (rule 5).
 *
 * Like lib/published/session.ts, which does the same for a session named by
 * year, round and type, these return what happened as a value and do not
 * throw, so the decisions can be tested without React.
 */

import { findPublishedSession, latestPublishedSession } from "./calendar.ts";
import type { PublishedSession } from "./calendar.ts";
import type { PublishedClient, SessionView } from "./published/client.ts";
import { isPublishedError, toPublishedFailure } from "./published/errors.ts";
import type { PublishedFailure } from "./published/errors.ts";
import type { PublishedIndex, SessionIdentity } from "./published/types.ts";

export type ChosenSessionLoad =
  /** The calendar could not be read, so nothing is known about any session. */
  | { readonly status: "no_calendar"; readonly failure: PublishedFailure }
  /** The calendar was read, and none of its sessions is published. Not a fault. */
  | { readonly status: "none_published"; readonly index: PublishedIndex }
  /** Neither the calendar nor a pointer has the key that was asked for. */
  | { readonly status: "unknown"; readonly index: PublishedIndex; readonly key: number }
  /** The calendar lists the session as published, and its pointer is not there. */
  | {
      readonly status: "unpublished";
      readonly index: PublishedIndex;
      readonly key: number;
      readonly listing: PublishedSession;
    }
  /** The session exists and could not be opened. `listing` is null when only the key is known. */
  | {
      readonly status: "failed";
      readonly index: PublishedIndex;
      readonly key: number;
      readonly listing: PublishedSession | null;
      readonly failure: PublishedFailure;
    }
  /** `recovered` is true once the view has been reopened after its generation went. */
  | {
      readonly status: "ready";
      readonly index: PublishedIndex;
      readonly key: number;
      /** Null when the pointer exists and the calendar does not list the session yet. */
      readonly listing: PublishedSession | null;
      readonly view: SessionView;
      readonly recovered: boolean;
    };

export type ReadyChosenSession = Extract<ChosenSessionLoad, { status: "ready" }>;

/**
 * Read the calendar and open a view on `requestedKey`, or on the most recent
 * published session when it is null.
 */
export async function loadChosenSession(
  client: PublishedClient,
  requestedKey: number | null
): Promise<ChosenSessionLoad> {
  let index: PublishedIndex;
  try {
    index = await client.index();
  } catch (error) {
    return { status: "no_calendar", failure: toPublishedFailure(error) };
  }
  const listing =
    requestedKey === null ? latestPublishedSession(index) : findPublishedSession(index, requestedKey);
  const key = requestedKey ?? listing?.key ?? null;
  if (key === null) {
    return { status: "none_published", index };
  }
  // A key the calendar does not list is still opened. The index is derived
  // after a pointer is written, so for a moment a published session is in the
  // bucket and not yet in the calendar; its pointer says who it is.
  return open(client, index, key, listing, false);
}

/**
 * Reopen a session whose pinned generation is gone: read the pointer again
 * and pin whatever it names now. At most once for each load, and not onto the
 * generation that just answered 404, for the reasons given at
 * `recoverSession` in lib/published/session.ts; both would reload for as long
 * as the files stay missing.
 */
export async function recoverChosenSession(
  client: PublishedClient,
  lost: ReadyChosenSession
): Promise<ChosenSessionLoad> {
  const { index, key, listing } = lost;
  const { generation } = lost.view.pointer;
  const stillGone = (message: string): ChosenSessionLoad => ({
    status: "failed",
    index,
    key,
    listing,
    failure: { code: "generation_gone", message, details: { session_key: key, generation } }
  });

  if (lost.recovered) {
    return stillGone("This session's published data was removed a second time while the page was open.");
  }
  const reopened = await open(client, index, key, listing, true);
  if (reopened.status === "ready" && reopened.view.pointer.generation === generation) {
    return stillGone(
      `The pointer of session ${key} still names generation ${generation.slice(0, 12)}, and files of it are missing.`
    );
  }
  return reopened;
}

async function open(
  client: PublishedClient,
  index: PublishedIndex,
  key: number,
  listing: PublishedSession | null,
  recovered: boolean
): Promise<ChosenSessionLoad> {
  try {
    // A recovery exists because the pointer this page read is out of date, so
    // it must not be answered from the same cache entry.
    const view = await client.openSession(key, { revalidate: recovered });
    return { status: "ready", index, key, listing, view, recovered };
  } catch (error) {
    if (isPublishedError(error, "not_published")) {
      return listing ? { status: "unpublished", index, key, listing } : { status: "unknown", index, key };
    }
    return { status: "failed", index, key, listing, failure: toPublishedFailure(error) };
  }
}

/** Who a session is, in the words a page heading uses. */
export type SessionDescription = {
  readonly year: number;
  /** Where the calendar has the meeting today; null when it has no entry for the session. */
  readonly round: number | null;
  readonly meetingName: string;
  readonly sessionName: string;
  readonly startTimeUtc: string | null;
  /** "Spielberg, Austria", or null when neither is known. */
  readonly place: string | null;
};

/**
 * Describe a session from the calendar where it lists the session, and from
 * the pointer otherwise. The round only ever comes from the calendar: the
 * pointer records the round at the time of the fetch, which a later calendar
 * change makes wrong.
 */
export function describeSession(
  listing: PublishedSession | null,
  identity: SessionIdentity | null
): SessionDescription | null {
  const place =
    [listing?.meeting?.location ?? identity?.location, listing?.meeting?.country ?? identity?.country]
      .filter(Boolean)
      .join(", ") || null;
  if (listing) {
    return {
      year: listing.year,
      round: listing.meeting?.round ?? null,
      meetingName: listing.meetingName,
      sessionName: listing.name,
      startTimeUtc: listing.startTimeUtc ?? identity?.start_time_utc ?? null,
      place
    };
  }
  if (identity) {
    return {
      year: identity.year,
      round: null,
      meetingName: identity.meeting_name,
      sessionName: identity.session_name,
      startTimeUtc: identity.start_time_utc,
      place
    };
  }
  return null;
}
