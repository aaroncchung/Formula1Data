/**
 * The site's URLs, built and read in one place.
 *
 * Everything the calendar decides is named in the query string and not in the
 * path. The site is a static export, which can only write a file for a path
 * it knows when it is built, and the seasons, meetings and sessions it shows
 * are whatever is published afterwards (AR-07).
 *
 *   /seasons                          every season of the calendar
 *   /season?year=2026                 one season
 *   /meeting?key=1288                 one race weekend, by F1's key for it
 *   /meeting?year=2026&round=8        the same, as the calendar numbers it today
 *   /session?key=11315                one session's dashboard
 *   /standings?year=2026              the championship tables of a season
 *   /strategy?key=11315               and /telemetry, /drivers, /teams: one
 *                                     session's summary, named as on /session,
 *                                     or the most recent published session
 *                                     when the address names none
 *
 * A session is always linked by its key. The link to its dashboard, and the
 * reading of an address that names a session, are in lib/published/lookup.ts
 * (`sessionHref`, `parseSessionAddress`), with the rest of what turns an
 * address into a session.
 *
 * A meeting is linked by its key too, once the index has one for it, which
 * is once one of its sessions is published. Until then its link carries the
 * round, which is looked up afresh on every visit and never kept (AR-20):
 * a link by round is good for the calendar it was made from and no longer.
 */

import { parseSessionAddress, sessionQuery } from "./published/lookup.ts";
import type { SessionAddress } from "./published/lookup.ts";
import type { IndexMeeting } from "./published/types.ts";

export const SEASONS_PATH = "/seasons";
export const STANDINGS_PATH = "/standings";
export const STRATEGY_PATH = "/strategy";
export const TELEMETRY_PATH = "/telemetry";
export const DRIVERS_PATH = "/drivers";
export const TEAMS_PATH = "/teams";

const SEASON_PATH = "/season";
const MEETING_PATH = "/meeting";

export function seasonHref(year: number): string {
  return `${SEASON_PATH}?year=${year}`;
}

/** How an address names a meeting: by F1's key for it, or by where the calendar has it today. */
export type MeetingAddress =
  | { readonly kind: "key"; readonly meetingKey: number }
  | { readonly kind: "round"; readonly year: number; readonly round: number };

/**
 * The link to a meeting of a season. By its key where the index has one, so
 * that the link still opens the same weekend after the calendar is
 * renumbered; by year and round for a meeting none of whose sessions is
 * published yet, which has no key to be linked by.
 */
export function meetingHref(year: number, meeting: Pick<IndexMeeting, "meeting_key" | "round">): string {
  return `${MEETING_PATH}?${meetingQuery(
    meeting.meeting_key === null
      ? { kind: "round", year, round: meeting.round }
      : { kind: "key", meetingKey: meeting.meeting_key }
  )}`;
}

/** A meeting's address as a query string, the way `meetingChoice` reads it back. */
export function meetingQuery(address: MeetingAddress): string {
  return address.kind === "key" ? `key=${address.meetingKey}` : `year=${address.year}&round=${address.round}`;
}

export function standingsHref(year: number): string {
  return `${STANDINGS_PATH}?year=${year}`;
}

/**
 * One of the pages that summarise a session (`/strategy`, `/telemetry`, ...),
 * on a chosen session. The session is spelled as it is for its dashboard, so
 * one reader takes both.
 */
export function sessionSummaryHref(path: string, sessionKey: number): string {
  return `${path}?${sessionQuery({ kind: "key", sessionKey })}`;
}

/** The part of `URLSearchParams` the readers use, so a test can pass a plain object. */
export type Query = { get(name: string): string | null };

/**
 * One value read from the query string. `invalid` is kept apart from `absent`
 * so that a mistyped link is answered as one, and not with the default a page
 * shows when it was given nothing.
 */
export type Param<T> =
  | { readonly status: "absent" }
  | { readonly status: "invalid"; readonly raw: string }
  | { readonly status: "ok"; readonly value: T };

const YEAR = /^[0-9]{4}$/;
const ROUND = /^[0-9]{1,2}$/;

/** `?year=2026`. */
export function yearParam(query: Query): Param<number> {
  return numberParam(query, "year", YEAR);
}

/** `?round=8`. A place in today's calendar, to be looked up there and not kept. */
export function roundParam(query: Query): Param<number> {
  return numberParam(query, "round", ROUND);
}

/** Which meeting the meeting page was asked for. */
export type MeetingChoice =
  | { readonly kind: "named"; readonly address: MeetingAddress }
  /** The address names no meeting at all. */
  | { readonly kind: "none" }
  /** The address tries to name a meeting and does not: a mistyped link. */
  | { readonly kind: "invalid" };

const MEETING_KEY = /^[0-9]{1,12}$/;
const MEETING_PARAMETERS = ["key", "year", "round"];

/**
 * Read `?key=1288` or `?year=2026&round=8`. A well-formed key wins when both
 * are given, as it does for a session: the key says which meeting, and the
 * round beside it may be from before the calendar moved.
 */
export function meetingChoice(query: Query): MeetingChoice {
  const key = query.get("key") ?? "";
  if (MEETING_KEY.test(key)) {
    return { kind: "named", address: { kind: "key", meetingKey: Number(key) } };
  }
  const year = yearParam(query);
  const round = roundParam(query);
  if (year.status === "ok" && round.status === "ok") {
    return { kind: "named", address: { kind: "round", year: year.value, round: round.value } };
  }
  const tried = MEETING_PARAMETERS.some((name) => (query.get(name) ?? "") !== "");
  return tried ? { kind: "invalid" } : { kind: "none" };
}

/** Which session a page that shows one session was asked for. */
export type SessionChoice =
  /** The address names none, so the page shows the most recent published session. */
  | { readonly kind: "latest" }
  | { readonly kind: "named"; readonly address: SessionAddress }
  /** The address tries to name a session and does not: a mistyped link, to be answered as one. */
  | { readonly kind: "invalid" };

const SESSION_PARAMETERS = ["key", "year", "round", "session"];

/**
 * Read which session a summary page is about. A session is named exactly as
 * it is on `/session`, by the same reader, so a link that works there works
 * here. What that reader cannot tell apart is an address that names no
 * session from one that names it wrongly, and a page that shows the latest
 * session for the first must not show it for the second.
 */
export function sessionChoice(query: Query): SessionChoice {
  const address = parseSessionAddress(query);
  if (address) {
    return { kind: "named", address };
  }
  const tried = SESSION_PARAMETERS.some((name) => (query.get(name) ?? "") !== "");
  return tried ? { kind: "invalid" } : { kind: "latest" };
}

function numberParam(query: Query, name: string, shape: RegExp): Param<number> {
  const raw = query.get(name);
  if (raw === null || raw === "") {
    return { status: "absent" };
  }
  return shape.test(raw) ? { status: "ok", value: Number(raw) } : { status: "invalid", raw };
}

/**
 * Whether a navigation entry is the one the reader is under. A season, a
 * meeting and a session all belong to "Seasons", so an entry can name more
 * paths than its own. `pathname` may carry the trailing slash the static
 * export adds.
 */
export function isUnderPath(pathname: string, paths: ReadonlyArray<string>): boolean {
  const current = withoutTrailingSlash(pathname);
  return paths.some((path) => {
    const root = withoutTrailingSlash(path);
    // Home is a prefix of everything, so it only matches itself.
    return root === "" ? current === "" : current === root || current.startsWith(`${root}/`);
  });
}

function withoutTrailingSlash(path: string): string {
  return path.replace(/\/+$/, "");
}
