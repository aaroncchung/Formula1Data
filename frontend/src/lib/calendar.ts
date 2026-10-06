/**
 * What the pages make of the published index: seasons, meetings, sessions and
 * which of them have data.
 *
 * The index is the calendar as it stands today, with a session key attached
 * to every session that is published. A round is only where a meeting sits in
 * this copy of the calendar: on 2026-10-05 a race was inserted at round 16 and
 * every later round moved (AR-20). So nothing here keeps or compares a round
 * across two reads. A session is named by its key, and a round is looked up
 * each time, for display and to follow a link that names one.
 */

import type { SessionEntry } from "./published/lookup.ts";
import type {
  IndexMeeting,
  IndexSeason,
  IndexSession,
  PublishedIndex,
  UnscheduledSession
} from "./published/types.ts";

/**
 * What a page can say about one session of the calendar. Published and
 * complete are separate states (rule 3): `partial` is published, with data
 * that fell short of a coverage bar. The two unpublished states differ only in
 * time, and neither is a fault.
 */
export type SessionAvailability = "complete" | "partial" | "not_published" | "scheduled";

export function sessionAvailability(session: IndexSession, now: number): SessionAvailability {
  if (session.session_key !== null) {
    return session.complete ? "complete" : "partial";
  }
  const start = timeOf(session.start_time_utc);
  // A session with no start time is one the calendar has not timed yet, so it
  // cannot have been run.
  return start === null || start > now ? "scheduled" : "not_published";
}

/** A published session, wherever the calendar has it now. */
export type PublishedSession = {
  /** F1's session key: the identity, and what every link to the session carries. */
  readonly key: number;
  readonly year: number;
  /** The short code: `FP1`, `Q`, `S`, `R`. */
  readonly type: string;
  readonly name: string;
  readonly startTimeUtc: string | null;
  readonly complete: boolean;
  readonly meetingName: string;
  /** The session's meeting in this index, or null when the calendar has no entry for the session. */
  readonly meeting: IndexMeeting | null;
};

/** Every published session of the index, the most recent first. */
export function publishedSessions(index: PublishedIndex): PublishedSession[] {
  const sessions: Array<{ session: PublishedSession; time: number; position: number }> = [];
  const add = (session: PublishedSession, fallbackDate: string | null) => {
    const time =
      timeOf(session.startTimeUtc) ??
      timeOf(fallbackDate) ??
      // Without any date the session still belongs to its season, at its start.
      Date.UTC(session.year, 0, 1);
    sessions.push({ session, time, position: sessions.length });
  };

  for (const season of index.seasons) {
    for (const meeting of season.meetings) {
      for (const session of meeting.sessions) {
        if (session.session_key !== null) {
          add(
            {
              key: session.session_key,
              year: season.year,
              type: session.type,
              name: session.name,
              startTimeUtc: session.start_time_utc,
              complete: session.complete === true,
              meetingName: meeting.name,
              meeting
            },
            meeting.date
          );
        }
      }
    }
  }
  for (const session of index.unscheduled) {
    add(fromUnscheduled(session), null);
  }

  // Two sessions with the same time keep the order the calendar lists them
  // in, the later entry counting as the more recent.
  return sessions
    .sort((left, right) => right.time - left.time || right.position - left.position)
    .map((item) => item.session);
}

/** The session the pages show when the reader has not chosen one. */
export function latestPublishedSession(index: PublishedIndex): PublishedSession | null {
  return publishedSessions(index)[0] ?? null;
}

/**
 * A published session in one line, for a list to choose from: "R8 · Austrian
 * Grand Prix · Race". The round is today's and only says where to look; a
 * session with partial data, or one the calendar cannot place, says so.
 */
export function sessionLabel(session: PublishedSession): string {
  const parts = session.meeting
    ? [`R${session.meeting.round}`, session.meetingName, session.name]
    : [session.meetingName, session.name, "not in the calendar"];
  return `${parts.join(" · ")}${session.complete ? "" : " (partial)"}`;
}

export function findSeason(index: PublishedIndex, year: number): IndexSeason | null {
  return index.seasons.find((season) => season.year === year) ?? null;
}

/** Published sessions of a year that the current calendar has no entry for, the earliest first. */
export function unscheduledSessions(index: PublishedIndex, year: number): PublishedSession[] {
  return index.unscheduled
    .filter((session) => session.year === year)
    .map(fromUnscheduled)
    .sort((left, right) => (timeOf(left.startTimeUtc) ?? 0) - (timeOf(right.startTimeUtc) ?? 0));
}

export type SeasonOverview = {
  readonly year: number;
  readonly meetingCount: number;
  /** Sessions the calendar lists, published or not. */
  readonly sessionCount: number;
  /** Published sessions, including those the calendar has no entry for. */
  readonly publishedCount: number;
  /** How many of the published sessions fell short of a coverage bar. */
  readonly partialCount: number;
  readonly unscheduledCount: number;
};

/**
 * One line for each season, the newest first. A year that only has sessions
 * the calendar cannot place is listed too: they are published, and leaving
 * the year out would hide them.
 */
export function seasonOverviews(index: PublishedIndex): SeasonOverview[] {
  const years = new Set([
    ...index.seasons.map((season) => season.year),
    ...index.unscheduled.map((session) => session.year)
  ]);
  return [...years]
    .sort((left, right) => right - left)
    .map((year) => {
      const sessions = (findSeason(index, year)?.meetings ?? []).flatMap((meeting) => meeting.sessions);
      const published = sessions.filter((session) => session.session_key !== null);
      const unscheduled = index.unscheduled.filter((session) => session.year === year);
      return {
        year,
        meetingCount: findSeason(index, year)?.meetings.length ?? 0,
        sessionCount: sessions.length,
        publishedCount: published.length + unscheduled.length,
        partialCount:
          published.filter((session) => session.complete !== true).length +
          unscheduled.filter((session) => !session.complete).length,
        unscheduledCount: unscheduled.length
      };
    });
}

export type MeetingLookup =
  | {
      readonly found: true;
      readonly year: number;
      readonly meeting: IndexMeeting;
      /** The meetings either side of it in the calendar, for moving between weekends. */
      readonly previous: IndexMeeting | null;
      readonly next: IndexMeeting | null;
    }
  /** `missing` is the first part of the link the calendar does not have. */
  | { readonly found: false; readonly missing: "year" | "round" };

/** The meeting a link names by year and round, as this index has it. */
export function findMeeting(index: PublishedIndex, year: number, round: number): MeetingLookup {
  const season = findSeason(index, year);
  if (!season) {
    return { found: false, missing: "year" };
  }
  const meetings = [...season.meetings].sort((left, right) => left.round - right.round);
  const position = meetings.findIndex((meeting) => meeting.round === round);
  const meeting = meetings[position];
  if (!meeting) {
    return { found: false, missing: "round" };
  }
  return {
    found: true,
    year: season.year,
    meeting,
    previous: meetings[position - 1] ?? null,
    next: meetings[position + 1] ?? null
  };
}

/** The first session that has not started, or null when the calendar holds none. */
export function nextSession(index: PublishedIndex, now: number): SessionEntry | null {
  let next: { entry: SessionEntry; time: number } | null = null;
  for (const season of index.seasons) {
    for (const meeting of season.meetings) {
      for (const session of meeting.sessions) {
        const time = timeOf(session.start_time_utc);
        if (time !== null && time > now && (next === null || time < next.time)) {
          next = { entry: { year: season.year, meeting, session }, time };
        }
      }
    }
  }
  return next?.entry ?? null;
}

/** One place the calendar visits, with every meeting held there. */
export type Venue = {
  /** Unique within one index. A key for a list, not an identity to keep. */
  readonly id: string;
  /** The town or circuit area the calendar names, or the meeting's name when it names none. */
  readonly place: string;
  readonly country: string | null;
  /** The meetings held here, the most recent first. */
  readonly meetings: ReadonlyArray<{ readonly year: number; readonly meeting: IndexMeeting }>;
  readonly publishedCount: number;
};

/**
 * The calendar grouped by place. The index names a meeting's location and
 * country and no circuit, so two circuits in one town would be one venue.
 */
export function venues(index: PublishedIndex): Venue[] {
  const grouped = new Map<string, { place: string; country: string | null; meetings: Venue["meetings"][number][] }>();
  for (const season of index.seasons) {
    for (const meeting of season.meetings) {
      const place = meeting.location ?? meeting.name;
      const id = `${meeting.country ?? ""}/${place}`;
      const venue = grouped.get(id) ?? { place, country: meeting.country, meetings: [] };
      venue.meetings.push({ year: season.year, meeting });
      grouped.set(id, venue);
    }
  }
  return [...grouped.entries()]
    .map(([id, venue]) => ({
      id,
      place: venue.place,
      country: venue.country,
      meetings: [...venue.meetings].sort(
        (left, right) => right.year - left.year || right.meeting.round - left.meeting.round
      ),
      publishedCount: venue.meetings
        .flatMap((item) => item.meeting.sessions)
        .filter((session) => session.session_key !== null).length
    }))
    .sort((left, right) => left.place.localeCompare(right.place, "en"));
}

function fromUnscheduled(session: UnscheduledSession): PublishedSession {
  return {
    key: session.session_key,
    year: session.year,
    type: session.type,
    name: session.name,
    startTimeUtc: session.start_time_utc,
    complete: session.complete,
    meetingName: session.meeting_name,
    meeting: null
  };
}

/** Milliseconds since the epoch, or null for a missing or unreadable date. */
function timeOf(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const time = Date.parse(value);
  return Number.isNaN(time) ? null : time;
}
