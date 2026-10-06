/**
 * What the standings page says about the published tables beyond the rows
 * themselves: which round they are after, and how a driver is named.
 */

import type { DriverStanding, Standings } from "./published/standings.ts";
import type { IndexSeason, PublishedIndex } from "./published/types.ts";

export type StandingsRound = {
  readonly round: number;
  /** The meeting the calendar has at that round today, or null when it has none there. */
  readonly meetingName: string | null;
  /** How many rounds the calendar has; null when the calendar is not at hand. */
  readonly of: number | null;
};

export type StandingsRounds = {
  readonly drivers: StandingsRound;
  readonly constructors: StandingsRound;
  /**
   * False while the two tables are a round apart. They are two requests to
   * Jolpica, so right after a race one can be ahead of the other, and a page
   * that printed one round for both would be wrong about one of them.
   */
  readonly agree: boolean;
};

/**
 * The round each table is after, named from the calendar. The standings carry
 * a round number and nothing else about it, so the name is looked up in the
 * season as the calendar has it now; it is a label for the number, and the
 * number is what the standings say.
 */
export function standingsRounds(standings: Standings, season: IndexSeason | null): StandingsRounds {
  const describe = (round: number): StandingsRound => ({
    round,
    meetingName: season?.meetings.find((meeting) => meeting.round === round)?.name ?? null,
    of: season ? season.meetings.length : null
  });
  return {
    drivers: describe(standings.rounds.drivers),
    constructors: describe(standings.rounds.constructors),
    agree: standings.rounds.drivers === standings.rounds.constructors
  };
}

/** "After round 16 of 23 · Bahrain Grand Prix". */
export function roundLabel(round: StandingsRound): string {
  const count = round.of === null ? `After round ${round.round}` : `After round ${round.round} of ${round.of}`;
  return round.meetingName ? `${count} · ${round.meetingName}` : count;
}

/**
 * The season the standings page opens on when the address names none: the
 * newest one that has a published session, since standings are published for
 * those. A calendar that already lists next year would otherwise open the
 * page on a season that has not started.
 */
export function defaultStandingsYear(index: PublishedIndex): number | null {
  const years = index.seasons.map((season) => season.year).sort((left, right) => right - left);
  const started = years.find((year) =>
    index.seasons.some(
      (season) =>
        season.year === year &&
        season.meetings.some((meeting) => meeting.sessions.some((session) => session.session_key !== null))
    )
  );
  return started ?? years[0] ?? null;
}

/** A driver's full name, or whatever part of it was published. */
export function driverName(driver: DriverStanding): string {
  return [driver.given_name, driver.family_name].filter(Boolean).join(" ");
}
