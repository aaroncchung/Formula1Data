/**
 * Finding a session in the index.
 *
 * A URL names a session by year, round and type because that is what a person
 * reads. None of it is identity: on 2026-10-05 round 16 became a different
 * race and every later round moved by one (AR-20). The index is therefore
 * consulted on every load to turn the three into F1's session key, and the key
 * is what the rest of the reader works with (rule 5).
 */

import type { IndexMeeting, IndexSession, PublishedIndex } from "./types.ts";

/** What a URL says about which session it wants. */
export type SessionRoute = {
  readonly year: number;
  readonly round: number;
  /** The short code, in any case: `R`, `q`, `FP1`. */
  readonly sessionType: string;
};

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

const YEAR = /^[0-9]{4}$/;
const ROUND = /^[0-9]{1,2}$/;
const SESSION_TYPE = /^[A-Za-z0-9]{1,4}$/;

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
