/**
 * What the session picker in the top bar offers, and what it has selected.
 *
 * The picker holds one thing: the key of the selected session. The season and
 * the event it shows are read back from the calendar for that key on every
 * render, and choosing a season or an event means choosing a session of it.
 * A round is never held as the selection, so a calendar that changes under an
 * open page cannot leave the picker pointing at a different race (AR-20).
 */

import { publishedSessions } from "./calendar.ts";
import type { PublishedSession } from "./calendar.ts";
import { findSession, isPublished, parseSessionAddress } from "./published/lookup.ts";
import type { IndexMeeting, PublishedIndex } from "./published/types.ts";
import { MEETING_PATH, isUnderPath, meetingChoice, roundParam, yearParam } from "./routes.ts";
import type { Query } from "./routes.ts";

export type PickerSession = {
  readonly key: number;
  readonly label: string;
};

export type PickerEvent = {
  /** The session the picker lands on when this event is chosen: its last published one. */
  readonly key: number;
  readonly label: string;
  /** The event's meeting in this index, or null for sessions the calendar has no entry for. */
  readonly meeting: IndexMeeting | null;
  /** In the order they were run. */
  readonly sessions: ReadonlyArray<PickerSession>;
};

export type PickerYear = {
  readonly year: number;
  /** The session the picker lands on when this season is chosen: its most recent one. */
  readonly key: number;
  /** In calendar order, with sessions the calendar cannot place at the end. */
  readonly events: ReadonlyArray<PickerEvent>;
};

export type PickerSelection = {
  readonly year: PickerYear;
  readonly event: PickerEvent;
  readonly session: PickerSession;
};

/**
 * Every published session, as seasons of events of sessions, the newest
 * season first. Only published sessions are offered, because the picker opens
 * a session's data and an unpublished session has none.
 */
export function pickerYears(index: PublishedIndex): PickerYear[] {
  const years = new Map<number, Map<IndexMeeting | string, PublishedSession[]>>();
  // Newest first, so the first session met for a season or an event is its
  // most recent one.
  for (const session of publishedSessions(index)) {
    const events = years.get(session.year) ?? new Map<IndexMeeting | string, PublishedSession[]>();
    const event = session.meeting ?? session.meetingName;
    events.set(event, [...(events.get(event) ?? []), session]);
    years.set(session.year, events);
  }

  return [...years.entries()]
    .sort(([left], [right]) => right - left)
    .flatMap(([year, events]) => {
      const sessions = [...events.values()];
      const latest = sessions.flat()[0];
      if (!latest) {
        return [];
      }
      return [
        {
          year,
          key: latest.key,
          events: sessions.flatMap(pickerEvent).sort(byCalendarOrder)
        }
      ];
    });
}

/** The selection for a key, or the most recent session when the key is null or is not offered. */
export function pickerSelection(years: ReadonlyArray<PickerYear>, key: number | null): PickerSelection | null {
  const wanted = key === null ? null : locate(years, key);
  if (wanted) {
    return wanted;
  }
  const latest = years[0];
  return latest ? locate(years, latest.key) : null;
}

/**
 * The session the current page is about, if its address names one that is
 * published. The picker starts there, so that it shows where the reader is
 * and not merely the latest race.
 *
 * `pathname` is the page's path. On a meeting's page `?key=` is F1's key for
 * the meeting, read as the page reads it, and the picker starts on the
 * meeting's latest published session: read as a session's key, `/meeting?key=1288`
 * named no session and the picker showed the latest race.
 */
export function pickerKeyForQuery(index: PublishedIndex, query: Query, pathname = ""): number | null {
  const years = pickerYears(index);
  if (isUnderPath(pathname, [MEETING_PATH])) {
    const choice = meetingChoice(query);
    if (choice.kind === "named" && choice.address.kind === "key") {
      const { meetingKey } = choice.address;
      const event = years.flatMap((year) => year.events).find((item) => item.meeting?.meeting_key === meetingKey);
      return event?.key ?? null;
    }
    // A meeting by year and round is found by the round, below.
  }
  // Read as the session page reads its own address, so the picker and the
  // page under it cannot disagree about which session a URL names: a key
  // wins over a round given beside it.
  const address = parseSessionAddress(query);
  if (address?.kind === "key") {
    return locate(years, address.sessionKey) ? address.sessionKey : null;
  }
  // `?year=&round=&session=` names a session by where the calendar has it
  // today. When that session is not published the picker still starts at its
  // meeting, through the year and round below.
  const named = address ? findSession(index, address.route) : null;
  if (named?.found && isPublished(named.entry.session)) {
    return named.entry.session.session_key;
  }
  const year = yearParam(query);
  if (year.status !== "ok") {
    return null;
  }
  const season = years.find((item) => item.year === year.value);
  const round = roundParam(query);
  if (!season || round.status !== "ok") {
    return season?.key ?? null;
  }
  return season.events.find((event) => event.meeting?.round === round.value)?.key ?? season.key;
}

function locate(years: ReadonlyArray<PickerYear>, key: number): PickerSelection | null {
  for (const year of years) {
    for (const event of year.events) {
      const session = event.sessions.find((item) => item.key === key);
      if (session) {
        return { year, event, session };
      }
    }
  }
  return null;
}

/** One event from its published sessions, given the most recent first. */
function pickerEvent(sessions: ReadonlyArray<PublishedSession>): PickerEvent[] {
  const latest = sessions[0];
  if (!latest) {
    return [];
  }
  return [
    {
      key: latest.key,
      label: latest.meeting
        ? `R${latest.meeting.round} · ${latest.meetingName}`
        : `${latest.meetingName} · not in the calendar`,
      meeting: latest.meeting,
      sessions: [...sessions].reverse().map((session) => ({
        key: session.key,
        label: `${session.type} · ${session.name}${session.complete ? "" : " (partial)"}`
      }))
    }
  ];
}

function byCalendarOrder(left: PickerEvent, right: PickerEvent): number {
  if (left.meeting && right.meeting) {
    return left.meeting.round - right.meeting.round;
  }
  if (left.meeting || right.meeting) {
    return left.meeting ? -1 : 1;
  }
  return left.label.localeCompare(right.label, "en");
}
