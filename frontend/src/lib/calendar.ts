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

import { isPublished } from "./published/lookup.ts";
import type { SessionEntry } from "./published/lookup.ts";
import type {
  IndexMeeting,
  IndexSeason,
  IndexSession,
  PublishedIndex,
  UnscheduledSession
} from "./published/types.ts";
import type { MeetingAddress } from "./routes.ts";

/**
 * What a page can say about one session of the calendar. Published and
 * complete are separate states (rule 3): `partial` is published, with data
 * that fell short of a coverage bar.
 *
 * There are three ways not to be published, and none is a fault.
 * `not_covered` is a kind of session the publisher does not take, which the
 * index says of each session (`in_scope`): it will not be published however
 * long ago it was run, so it is neither awaited nor still to come. The other
 * two are sessions the publisher does take, and differ only in time.
 */
export type SessionAvailability = "complete" | "partial" | "not_published" | "scheduled" | "not_covered";

export function sessionAvailability(session: IndexSession, now: number): SessionAvailability {
  // Published is published, whatever the index says of the session's kind.
  if (isPublished(session)) {
    return session.complete ? "complete" : "partial";
  }
  if (!session.in_scope) {
    return "not_covered";
  }
  const start = timeOf(session.start_time_utc);
  // A session with no start time is one the calendar has not timed yet, so it
  // cannot have been run. One whose start has passed has started: whether it
  // has finished the calendar cannot say, and what a page says of
  // `not_published` has to be true of a race that is still going on.
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
        if (isPublished(session)) {
          add(
            {
              key: session.session_key,
              year: season.year,
              type: session.type,
              name: session.name,
              startTimeUtc: session.start_time_utc,
              complete: session.complete,
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
  /** Sessions the calendar lists, published or not, covered or not. */
  readonly sessionCount: number;
  /**
   * Sessions the publisher takes: the ones the calendar marks as in scope,
   * and any that are published all the same, in the calendar or out of it.
   * This is what the published count is out of.
   */
  readonly coveredCount: number;
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
      const published = sessions.filter(isPublished);
      const unscheduled = index.unscheduled.filter((session) => session.year === year);
      return {
        year,
        meetingCount: findSeason(index, year)?.meetings.length ?? 0,
        sessionCount: sessions.length,
        coveredCount: sessions.filter(isCovered).length + unscheduled.length,
        publishedCount: published.length + unscheduled.length,
        partialCount:
          published.filter((session) => !session.complete).length +
          unscheduled.filter((session) => !session.complete).length,
        unscheduledCount: unscheduled.length
      };
    });
}

/** What of a race weekend the publisher takes, and how much of that is published. */
export type MeetingCoverage = {
  readonly published: number;
  /** Sessions in scope, and any that are published all the same. */
  readonly covered: number;
  /** The names of the sessions the publisher does not take, in the order of the weekend. */
  readonly notCovered: ReadonlyArray<string>;
};

export function meetingCoverage(meeting: IndexMeeting): MeetingCoverage {
  return {
    published: meeting.sessions.filter(isPublished).length,
    covered: meeting.sessions.filter(isCovered).length,
    notCovered: meeting.sessions.filter((session) => !isCovered(session)).map((session) => session.name)
  };
}

/** A weekend's coverage in a sentence or two, so that an unpublished practice is not read as a missing one. */
export function describeMeetingCoverage(coverage: MeetingCoverage): string {
  const { published, covered, notCovered } = coverage;
  const sentences: string[] = [];
  if (covered === 0) {
    sentences.push("None of this weekend's sessions is of a kind this site publishes.");
  } else if (published === 0) {
    sentences.push(
      covered === 1
        ? "The one session of this weekend that this site covers is not published yet."
        : `None of the ${covered} sessions of this weekend that this site covers is published yet.`
    );
  } else {
    sentences.push(`${published} of the ${covered} ${covered === 1 ? "session" : "sessions"} this site covers ${published === 1 ? "is" : "are"} published.`);
  }
  if (covered > 0 && notCovered.length > 0) {
    sentences.push(`Not covered: ${notCovered.join(", ")}.`);
  }
  return sentences.join(" ");
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
  | { readonly found: false; readonly missing: "year" | "round" | "key" };

/** The meeting an address names, as this index has it. */
export function lookUpMeeting(index: PublishedIndex, address: MeetingAddress): MeetingLookup {
  return address.kind === "key"
    ? findMeetingByKey(index, address.meetingKey)
    : findMeeting(index, address.year, address.round);
}

/** The meeting a link names by year and round, as this index has it. */
export function findMeeting(index: PublishedIndex, year: number, round: number): MeetingLookup {
  const season = findSeason(index, year);
  if (!season) {
    return { found: false, missing: "year" };
  }
  return placedIn(season, (meeting) => meeting.round === round) ?? { found: false, missing: "round" };
}

/**
 * The meeting that has F1's key for it, in whichever season and at whichever
 * round the calendar has it now. A meeting has a key once one of its sessions
 * is published, so a key the calendar does not have names nothing here.
 */
export function findMeetingByKey(index: PublishedIndex, meetingKey: number): MeetingLookup {
  for (const season of index.seasons) {
    const placed = placedIn(season, (meeting) => meeting.meeting_key === meetingKey);
    if (placed) {
      return placed;
    }
  }
  return { found: false, missing: "key" };
}

/** A meeting of a season with the meetings either side of it, in the order of the rounds. */
function placedIn(season: IndexSeason, wanted: (meeting: IndexMeeting) => boolean): MeetingLookup | null {
  const meetings = [...season.meetings].sort((left, right) => left.round - right.round);
  const position = meetings.findIndex(wanted);
  const meeting = meetings[position];
  if (!meeting) {
    return null;
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

/** A meeting with the season it is in. */
export type SeasonMeeting = { readonly year: number; readonly meeting: IndexMeeting };

/** One circuit of the calendar, with every meeting held at it. */
export type Circuit = {
  /** F1's key for the circuit, which is what makes two meetings the same circuit. */
  readonly key: number;
  /** F1's short name for the circuit, such as Spielberg; the place, when the calendar gives the circuit no name. */
  readonly name: string;
  readonly location: string | null;
  readonly country: string | null;
  /** The meetings held here, the most recent first. */
  readonly meetings: ReadonlyArray<SeasonMeeting>;
  readonly publishedCount: number;
};

export type CircuitGuide = {
  /** By name. */
  readonly circuits: Circuit[];
  /**
   * Meetings the calendar names no circuit for, the newest season first and
   * in the order of its rounds. The calendar learns a meeting's circuit from
   * F1's own session information, so it has none for a meeting until one of
   * its sessions is published.
   */
  readonly unidentified: ReadonlyArray<SeasonMeeting>;
};

/**
 * The calendar grouped by circuit, by F1's key for each.
 *
 * A meeting with no circuit key is not put with a circuit by the name of its
 * town or its country. That would be a guess, and wrong where a town has had
 * two circuits or a race has moved within a country. It is listed apart, as
 * a meeting whose circuit is not known yet.
 */
export function circuits(index: PublishedIndex): CircuitGuide {
  const grouped = new Map<number, SeasonMeeting[]>();
  const unidentified: SeasonMeeting[] = [];
  for (const season of index.seasons) {
    for (const meeting of season.meetings) {
      const entry = { year: season.year, meeting };
      if (meeting.circuit_key === null) {
        unidentified.push(entry);
      } else {
        grouped.set(meeting.circuit_key, [...(grouped.get(meeting.circuit_key) ?? []), entry]);
      }
    }
  }
  return {
    circuits: [...grouped.entries()]
      .map(([key, held]) => {
        const meetings = [...held].sort(
          (left, right) => right.year - left.year || right.meeting.round - left.meeting.round
        );
        // What the circuit is called is taken from the most recent meeting that says.
        const named = meetings.find((item) => item.meeting.circuit_name !== null)?.meeting ?? meetings[0].meeting;
        return {
          key,
          name: named.circuit_name ?? named.location ?? named.name,
          location: named.location,
          country: named.country,
          meetings,
          publishedCount: meetings.flatMap((item) => item.meeting.sessions).filter(isPublished).length
        };
      })
      .sort((left, right) => left.name.localeCompare(right.name, "en") || left.key - right.key),
    unidentified: unidentified.sort(
      (left, right) => right.year - left.year || left.meeting.round - right.meeting.round
    )
  };
}

/** Whether the publisher takes a session: it is in scope, or it is published all the same. */
function isCovered(session: IndexSession): boolean {
  return session.in_scope || isPublished(session);
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
