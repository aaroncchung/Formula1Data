/**
 * Finding a session in the index.
 *
 * A URL can name a session two ways. By F1's session key, `?key=11315`, which
 * is the session's identity and is what the site's own links carry. Or by
 * year, round and type, because that is what a person reads and types. None
 * of the three is identity: on 2026-10-05 round 16 became a different race
 * and every later round moved by one (AR-20). A route is therefore turned
 * into a key through the index on every load, and the key is what the rest of
 * the reader works with (rule 5).
 */

import { isSessionKey } from "./layout.ts";
import type { IndexMeeting, IndexSession, PublishedIndex, SessionIdentity, UnscheduledSession } from "./types.ts";

/** A session named by where the calendar puts it. */
export type SessionRoute = {
  readonly year: number;
  readonly round: number;
  /** The short code, in any case: `R`, `q`, `FP1`. */
  readonly sessionType: string;
};

/** What a URL says about which session it wants. */
export type SessionAddress =
  | { readonly kind: "key"; readonly sessionKey: number }
  | { readonly kind: "route"; readonly route: SessionRoute };

/** A session where the index places it now. */
export type SessionEntry = {
  readonly year: number;
  readonly meeting: IndexMeeting;
  readonly session: IndexSession;
};

export type SessionLookup =
  | { readonly found: true; readonly entry: SessionEntry }
  /** `missing` is the first part of the route the calendar does not have. */
  | { readonly found: false; readonly missing: "year" | "round" | "session" };

/**
 * Where the index has a published session: at an entry of the calendar, or in
 * its list of sessions the calendar has no entry for. The second kind has no
 * round, so a key is the only way to name it.
 */
export type SessionPlace =
  | { readonly kind: "calendar"; readonly entry: SessionEntry }
  | { readonly kind: "unscheduled"; readonly session: UnscheduledSession };

/** What a page prints above a session. */
export type SessionHeading = {
  readonly year: number;
  /** The round the calendar gives the meeting today; null when it has no entry for the session. */
  readonly round: number | null;
  readonly meetingName: string;
  readonly sessionName: string;
  readonly startTimeUtc: string | null;
  readonly location: string | null;
  readonly country: string | null;
  /**
   * Why there is or is not a round. `calendar`: the index places the session.
   * `unscheduled`: the index lists it as published outside the calendar.
   * `unplaced`: the index does not mention it, or could not be read, and the
   * heading comes from the session's own pointer.
   */
  readonly placement: "calendar" | "unscheduled" | "unplaced";
};

const YEAR = /^[0-9]{4}$/;
const ROUND = /^[0-9]{1,2}$/;
const SESSION_TYPE = /^[A-Za-z0-9]{1,4}$/;
const SESSION_KEY = /^[0-9]{1,12}$/;

/**
 * Read `?key=11315` or `?year=2026&round=8&session=R`.
 *
 * A well-formed key wins when both are given: the key says which session, and
 * the round beside it may be out of date. Returns null when neither form is
 * complete and well formed, so that a mistyped link is told apart from a
 * session that does not exist.
 */
export function parseSessionAddress(query: { get(name: string): string | null }): SessionAddress | null {
  const key = query.get("key") ?? "";
  if (SESSION_KEY.test(key)) {
    const sessionKey = Number(key);
    if (isSessionKey(sessionKey)) {
      return { kind: "key", sessionKey };
    }
  }
  const route = parseSessionRoute(query);
  return route ? { kind: "route", route } : null;
}

/**
 * An address as the query string that `parseSessionAddress` reads back to the
 * same address. One spelling for each, so it also serves to tell whether two
 * addresses are the same.
 */
export function sessionQuery(address: SessionAddress): string {
  if (address.kind === "key") {
    return `key=${address.sessionKey}`;
  }
  const { year, round, sessionType } = address.route;
  return `year=${year}&round=${round}&session=${encodeURIComponent(sessionType.toUpperCase())}`;
}

/**
 * The link to a session's page. Give it the key whenever the session has one:
 * a link by round shows another race once the calendar moves. A route is for
 * a session that is not published yet and so has no key.
 */
export function sessionHref(address: SessionAddress): string {
  return `/session?${sessionQuery(address)}`;
}

/**
 * Read `?year=2026&round=8&session=R`. Returns null unless all three are
 * present and well formed, so that a mistyped link is told apart from a
 * session the calendar does not have.
 */
export function parseSessionRoute(query: { get(name: string): string | null }): SessionRoute | null {
  const year = query.get("year") ?? "";
  const round = query.get("round") ?? "";
  const sessionType = query.get("session") ?? "";
  if (!YEAR.test(year) || !ROUND.test(round) || !SESSION_TYPE.test(sessionType)) {
    return null;
  }
  return { year: Number(year), round: Number(round), sessionType: sessionType.toUpperCase() };
}

/** The calendar entry a route names in this index. */
export function findSession(index: PublishedIndex, route: SessionRoute): SessionLookup {
  const season = index.seasons.find((item) => item.year === route.year);
  if (!season) {
    return { found: false, missing: "year" };
  }
  const meeting = season.meetings.find((item) => item.round === route.round);
  if (!meeting) {
    return { found: false, missing: "round" };
  }
  const wanted = route.sessionType.trim().toUpperCase();
  const session = meeting.sessions.find((item) => item.type.toUpperCase() === wanted);
  if (!session) {
    return { found: false, missing: "session" };
  }
  return { found: true, entry: { year: season.year, meeting, session } };
}

/**
 * Where this index has the session with this key, or null when it does not
 * mention it. Null is not "unpublished": the index is derived after a pointer
 * is written and is cached on its own, so only the pointer can say that.
 */
export function findSessionByKey(index: PublishedIndex, sessionKey: number): SessionPlace | null {
  for (const season of index.seasons) {
    for (const meeting of season.meetings) {
      const session = meeting.sessions.find((item) => item.session_key === sessionKey);
      if (session) {
        return { kind: "calendar", entry: { year: season.year, meeting, session } };
      }
    }
  }
  const unscheduled = index.unscheduled.find((item) => item.session_key === sessionKey);
  return unscheduled ? { kind: "unscheduled", session: unscheduled } : null;
}

/**
 * The heading of a session the calendar places. Everything comes from the
 * index entry, so the heading reads the same whether the session turned out
 * to be published, unpublished or broken, and the round is today's.
 */
export function headingOfEntry(entry: SessionEntry): SessionHeading {
  const { meeting, session } = entry;
  return {
    year: entry.year,
    round: meeting.round,
    meetingName: meeting.name,
    sessionName: session.name,
    startTimeUtc: session.start_time_utc ?? meeting.date,
    location: meeting.location,
    country: meeting.country,
    placement: "calendar"
  };
}

export function headingOfUnscheduled(session: UnscheduledSession): SessionHeading {
  return {
    year: session.year,
    round: null,
    meetingName: session.meeting_name,
    sessionName: session.name,
    startTimeUtc: session.start_time_utc,
    location: null,
    country: null,
    placement: "unscheduled"
  };
}

/**
 * The heading of a session from its own pointer, for when the index has
 * nothing to say about it. The pointer knows who the session is and not where
 * it sits in the calendar, so there is no round.
 */
export function headingOfIdentity(identity: SessionIdentity): SessionHeading {
  return {
    year: identity.year,
    round: null,
    meetingName: identity.meeting_name,
    sessionName: identity.session_name,
    startTimeUtc: identity.start_time_utc,
    location: identity.location,
    country: identity.country,
    placement: "unplaced"
  };
}
