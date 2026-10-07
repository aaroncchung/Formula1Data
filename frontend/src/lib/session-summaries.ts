/**
 * What the home page, `/drivers` and `/teams` read from a session's view, and
 * what they make of it.
 *
 * `/strategy` and `/telemetry` show a tab of the session dashboard on a page
 * of its own and read with that tab's reader. These three pages show
 * something no tab does, so they have readers of their own; each file is
 * still read through `ARTIFACTS`, which is where a file's path, its type and
 * the check of its shape are, once for every page that reads it.
 *
 * Each reader asks for a few small files and never the laps, the telemetry
 * or the position replay (AR-07). A file the generation does not hold is
 * null, not a failure: a practice session has no classification, and the page
 * leaves that figure blank.
 */

import { ARTIFACTS, readIfListed } from "./published/artifacts.ts";
import type { SessionView } from "./published/client.ts";
import type { Driver, IdealLaps, RacePace, Result, SessionSummary } from "./published/types.ts";
import { classifiedPlace, resultPosition } from "./results-view.ts";

export type SessionFigures = {
  readonly summary: SessionSummary | null;
  readonly idealLaps: IdealLaps | null;
};

/** The headline figures of a session: its size, and who left least time on the track. */
export async function readSessionFigures(view: SessionView): Promise<SessionFigures> {
  const [summary, idealLaps] = await Promise.all([
    readIfListed(view, ARTIFACTS.summary),
    readIfListed(view, ARTIFACTS.idealLaps)
  ]);
  return { summary, idealLaps };
}

/**
 * The pace analysis on its own, for the home page's chart. The race-pace
 * tab's reader (`readRacePace` in artifacts.ts) also reads every lap of the
 * session, which the home page does not show.
 */
export function readPaceAnalysis(view: SessionView): Promise<RacePace | null> {
  return readIfListed(view, ARTIFACTS.racePace);
}

/** The drivers of a session with what the driver and team cards show beside them. */
export type FieldArtifacts = {
  readonly drivers: ReadonlyArray<Driver>;
  readonly results: ReadonlyArray<Result> | null;
  readonly racePace: RacePace | null;
  readonly idealLaps: IdealLaps | null;
};

export async function readField(view: SessionView): Promise<FieldArtifacts> {
  // The drivers are the page: without them it is a failure, where the three
  // beside them only leave a figure blank.
  const [drivers, results, racePace, idealLaps] = await Promise.all([
    ARTIFACTS.drivers.read(view),
    readIfListed(view, ARTIFACTS.results),
    readIfListed(view, ARTIFACTS.racePace),
    readIfListed(view, ARTIFACTS.idealLaps)
  ]);
  return { drivers, results, racePace, idealLaps };
}

export type DriverCard = {
  readonly driver: Driver;
  /** The place the driver was classified in; null with no result, or one that gives no place. */
  readonly finish: number | null;
  /** What the classification prints for the driver, "3" or "R"; null when the driver has no result. */
  readonly classification: string | null;
  readonly medianLapMs: number | null;
  readonly idealLapMs: number | null;
};

export function driverCards(field: FieldArtifacts): DriverCard[] {
  return field.drivers.map((driver) => {
    const result = field.results?.find((row) => row.driver_code === driver.code) ?? null;
    return {
      driver,
      finish: result ? classifiedPlace(result) : null,
      classification: result ? resultPosition(result).text : null,
      medianLapMs: field.racePace?.drivers.find((row) => row.driver_code === driver.code)?.median_lap_ms ?? null,
      idealLapMs: field.idealLaps?.rows.find((row) => row.driver_code === driver.code)?.ideal_lap_ms ?? null
    };
  });
}

export type TeamCard = {
  /** Unique within the session. */
  readonly id: string;
  readonly name: string;
  readonly color: string | null;
  readonly drivers: ReadonlyArray<Driver>;
  /** Points scored in this session; null when none were published for the team's drivers. */
  readonly points: number | null;
  /** The better of the places the team's drivers were classified in; null when neither has one. */
  readonly bestFinish: number | null;
  /** Laps that counted towards race pace; null when the session has no pace analysis. */
  readonly paceLaps: number | null;
};

/** The session's drivers grouped into teams, in the order the session lists them. */
export function teamCards(field: FieldArtifacts): TeamCard[] {
  const teams = new Map<string, { name: string; color: string | null; drivers: Driver[] }>();
  for (const driver of field.drivers) {
    // F1's driver list can name no team for a driver. Such drivers are shown
    // together, under what the list says of them, and not left off the page.
    const id = driver.team ? driver.team.team_id || driver.team.name : NO_TEAM_ID;
    const team = teams.get(id) ?? {
      name: driver.team?.name ?? "No team listed",
      color: driver.team?.color ?? null,
      drivers: []
    };
    team.drivers.push(driver);
    teams.set(id, team);
  }
  return [...teams.entries()].map(([id, team]) => {
    const results = (field.results ?? []).filter((row) => team.drivers.some((driver) => driver.code === row.driver_code));
    const pace = (field.racePace?.drivers ?? []).filter((row) =>
      team.drivers.some((driver) => driver.code === row.driver_code)
    );
    const places = results.map(classifiedPlace).filter((place): place is number => place !== null);
    // A team the classification leaves out scored nothing, which is a true
    // zero. A team whose rows carry no points at all is a provisional order,
    // which has none to give.
    const hasPoints = results.length === 0 || results.some((row) => row.points !== null);
    return {
      id,
      name: team.name,
      color: team.color,
      drivers: team.drivers,
      points: field.results && hasPoints ? results.reduce((sum, row) => sum + (row.points ?? 0), 0) : null,
      bestFinish: places.length ? Math.min(...places) : null,
      paceLaps: field.racePace ? pace.reduce((sum, row) => sum + row.lap_count, 0) : null
    };
  });
}

// Not a team id the publisher can write: those are lower case with hyphens.
const NO_TEAM_ID = "(no team)";
