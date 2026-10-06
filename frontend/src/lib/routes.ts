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
 *   /meeting?year=2026&round=8        one race weekend, as the calendar numbers it today
 *   /session?key=11315                one session's dashboard
 *   /standings?year=2026              the championship tables of a season
 *   /strategy?key=11315               and /telemetry, /drivers, /teams: one
 *                                     session's summary, the most recent
 *                                     published session when no key is given
 *
 * A session is always linked by its key. The link to its dashboard, and the
 * reading of an address that names a session, are in lib/published/lookup.ts
 * (`sessionHref`, `parseSessionAddress`), with the rest of what turns an
 * address into a session. A meeting has no key in the index, so its link
 * carries the round, which is looked up afresh on every visit and never kept
 * (AR-20).
 */

import { sessionQuery } from "./published/lookup.ts";

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

export function meetingHref(year: number, round: number): string {
  return `${MEETING_PATH}?year=${year}&round=${round}`;
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
// Fifteen digits at most, so that the number read is always a safe integer
// and therefore a session key (`isSessionKey`).
const SESSION_KEY = /^[0-9]{1,15}$/;

/** `?year=2026`. */
export function yearParam(query: Query): Param<number> {
  return numberParam(query, "year", YEAR);
}

/** `?round=8`. A place in today's calendar, to be looked up there and not kept. */
export function roundParam(query: Query): Param<number> {
  return numberParam(query, "round", ROUND);
}

/** `?key=11315`. */
export function sessionKeyParam(query: Query): Param<number> {
  return numberParam(query, "key", SESSION_KEY);
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
