/**
 * What the pages that summarise one session read from its view, and what they
 * make of it: the home page, `/strategy`, `/telemetry`, `/drivers` and
 * `/teams`.
 *
 * Each reader asks the pinned generation for a few small files and nothing
 * else, so a summary page costs a handful of requests and never the telemetry
 * laps or the position replay (AR-07). A file the generation does not hold is
 * read as null, not as a failure: a practice session has no pit stops, and a
 * page says so in the one panel it concerns.
 */

import type {
  Driver,
  IdealLapsResult,
  PitStop,
  RacePaceResult,
  Result,
  SessionSummary,
  Stint,
  StrategyResult
} from "../types/domain";
import type { SessionView } from "./published/client.ts";
import { PublishedDataError } from "./published/errors.ts";
import type { TelemetryIndex } from "./static-api-core.ts";

export const SUMMARY_PATH = "summary.json";
export const DRIVERS_PATH = "drivers.json";
export const RESULTS_PATH = "results.json";
export const STINTS_PATH = "stints.json";
export const PIT_STOPS_PATH = "pit-stops.json";
export const STRATEGY_PATH = "analysis/strategy.json";
export const RACE_PACE_PATH = "analysis/race-pace.json";
export const IDEAL_LAPS_PATH = "analysis/ideal-laps.json";
export const TELEMETRY_INDEX_PATH = "telemetry/index.json";

export type SessionFigures = {
  readonly summary: SessionSummary | null;
  readonly idealLaps: IdealLapsResult | null;
};

/** The headline figures of a session: its size, and who left least time on the track. */
export async function readSessionFigures(view: SessionView): Promise<SessionFigures> {
  const [summary, idealLaps] = await Promise.all([
    readOptionalRecord<SessionSummary>(view, SUMMARY_PATH, []),
    readOptionalRecord<IdealLapsResult>(view, IDEAL_LAPS_PATH, ["rows"])
  ]);
  return { summary, idealLaps };
}

export function readRacePace(view: SessionView): Promise<RacePaceResult | null> {
  return readOptionalRecord<RacePaceResult>(view, RACE_PACE_PATH, ["drivers"]);
}

export type StrategyArtifacts = {
  readonly stints: Stint[] | null;
  readonly pitStops: PitStop[] | null;
  readonly strategy: StrategyResult | null;
};

export async function readStrategy(view: SessionView): Promise<StrategyArtifacts> {
  const [stints, pitStops, strategy] = await Promise.all([
    readOptionalList<Stint>(view, STINTS_PATH),
    readOptionalList<PitStop>(view, PIT_STOPS_PATH),
    readOptionalRecord<StrategyResult>(view, STRATEGY_PATH, ["caveats"])
  ]);
  return { stints, pitStops, strategy };
}

/** The drivers of a session with what the driver and team cards show beside them. */
export type FieldArtifacts = {
  readonly drivers: Driver[];
  readonly results: Result[] | null;
  readonly racePace: RacePaceResult | null;
  readonly idealLaps: IdealLapsResult | null;
};

export async function readField(view: SessionView): Promise<FieldArtifacts> {
  // The drivers are the page: without them it is a failure, where the three
  // beside them only leave a figure blank.
  const [drivers, results, racePace, idealLaps] = await Promise.all([
    readList<Driver>(view, DRIVERS_PATH),
    readOptionalList<Result>(view, RESULTS_PATH),
    readRacePace(view),
    readOptionalRecord<IdealLapsResult>(view, IDEAL_LAPS_PATH, ["rows"])
  ]);
  return { drivers, results, racePace, idealLaps };
}

export function readTelemetryIndex(view: SessionView): Promise<TelemetryIndex | null> {
  return readOptionalRecord<TelemetryIndex>(view, TELEMETRY_INDEX_PATH, ["laps"]);
}

export type DriverCard = {
  readonly driver: Driver;
  /** The classified position, or null when the driver has no result. */
  readonly finish: number | null;
  readonly medianLapMs: number | null;
  readonly idealLapMs: number | null;
};

export function driverCards(field: FieldArtifacts): DriverCard[] {
  return field.drivers.map((driver) => ({
    driver,
    finish: field.results?.find((row) => row.driver_code === driver.code)?.position ?? null,
    medianLapMs: field.racePace?.drivers.find((row) => row.driver_code === driver.code)?.median_lap_ms ?? null,
    idealLapMs: field.idealLaps?.rows.find((row) => row.driver_code === driver.code)?.ideal_lap_ms ?? null
  }));
}

export type TeamCard = {
  /** Unique within the session. */
  readonly id: string;
  readonly name: string;
  readonly color: string | null;
  readonly drivers: Driver[];
  /** Points scored in this session; null when it has no classification. */
  readonly points: number | null;
  /** The better of the team's classified positions; null when neither driver has one. */
  readonly bestFinish: number | null;
  /** Laps that counted towards race pace; null when the session has no pace analysis. */
  readonly paceLaps: number | null;
};

/** The session's drivers grouped into teams, in the order the session lists them. */
export function teamCards(field: FieldArtifacts): TeamCard[] {
  const teams = new Map<string, { name: string; color: string | null; drivers: Driver[] }>();
  for (const driver of field.drivers) {
    const id = driver.team.team_id || driver.team.name;
    const team = teams.get(id) ?? { name: driver.team.name, color: driver.team.color ?? null, drivers: [] };
    team.drivers.push(driver);
    teams.set(id, team);
  }
  return [...teams.entries()].map(([id, team]) => {
    const results = (field.results ?? []).filter((row) => team.drivers.some((driver) => driver.code === row.driver_code));
    const pace = (field.racePace?.drivers ?? []).filter((row) =>
      team.drivers.some((driver) => driver.code === row.driver_code)
    );
    return {
      id,
      name: team.name,
      color: team.color,
      drivers: team.drivers,
      points: field.results ? results.reduce((sum, row) => sum + (row.points ?? 0), 0) : null,
      bestFinish: results.length ? Math.min(...results.map((row) => row.position)) : null,
      paceLaps: field.racePace ? pace.reduce((sum, row) => sum + row.lap_count, 0) : null
    };
  });
}

export type TelemetryLap = TelemetryIndex["laps"][number];

/**
 * The two laps the comparison starts on: the first lap that has telemetry,
 * and the first lap of another driver. Null when fewer than two laps have any.
 */
export function defaultTelemetryLaps(
  laps: ReadonlyArray<TelemetryLap>
): { readonly a: TelemetryLap; readonly b: TelemetryLap } | null {
  const a = laps[0];
  const b = laps.find((lap) => lap.driver_code !== a?.driver_code) ?? laps[1];
  return a && b ? { a, b } : null;
}

async function readOptionalList<T>(view: SessionView, path: string): Promise<T[] | null> {
  return view.has(path) ? readList<T>(view, path) : null;
}

/**
 * Read an artifact that is a list. Only that much is checked, as in
 * lib/published/artifacts.ts: a component that maps over something else takes
 * the page down, while the shape of each row is vouched for by the manifest's
 * format version (rule 7).
 */
async function readList<T>(view: SessionView, path: string): Promise<T[]> {
  const payload = await view.read<unknown>(path);
  if (!Array.isArray(payload)) {
    throw new PublishedDataError("invalid_artifact", `${path} is not a list.`, { path });
  }
  const rows: unknown[] = payload;
  return rows as T[];
}

/**
 * Read an artifact that is an object, when the generation holds it. `lists`
 * names the fields a page maps over, which are checked for the same reason a
 * list artifact is.
 */
async function readOptionalRecord<T>(
  view: SessionView,
  path: string,
  lists: ReadonlyArray<string>
): Promise<T | null> {
  if (!view.has(path)) {
    return null;
  }
  const payload = await view.read<unknown>(path);
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new PublishedDataError("invalid_artifact", `${path} is not an object.`, { path });
  }
  const fields: Record<string, unknown> = { ...payload };
  for (const field of lists) {
    if (!Array.isArray(fields[field])) {
      throw new PublishedDataError("invalid_artifact", `${path} has no list named ${field}.`, { path, field });
    }
  }
  return payload as T;
}
