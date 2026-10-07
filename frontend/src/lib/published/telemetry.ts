/**
 * The telemetry tab's reads.
 *
 * A session's telemetry is one file for each driver, holding every lap of
 * theirs that has any, at about a megabyte for a race distance; twenty or so
 * of them is most of what a session weighs. The tab reads the index that
 * lists the laps when it opens, and after that only the files of the drivers
 * it is asked to compare. A view that shares its reads (share.ts) keeps a
 * driver's file once it has it, so comparing another lap of the same driver
 * asks for nothing.
 *
 * The index says everything a lap is chosen by: its time, its compound, and
 * whether it is a lap worth comparing (accurately timed, not deleted, not
 * into or out of the pits). The laps of the session are not read here.
 */

import { compareLaps } from "../telemetry-compare.ts";
import type { ComparedLap, TelemetryComparison } from "../telemetry-compare.ts";
import { ARTIFACTS, readIfListed, readRecord, requireListed } from "./artifacts.ts";
import type { SessionView } from "./client.ts";
import { isPublishedError } from "./errors.ts";
import type { Compound, Corners, Driver, DriverTelemetry, TelemetryDriverEntry, TelemetryIndex } from "./types.ts";

/** One lap of one driver. */
export type LapRef = { readonly driver: string; readonly lap: number };

export type LapPair = readonly [LapRef, LapRef];

/** A lap that has telemetry, with what the index says of it. */
export type TelemetryLapChoice = {
  readonly driver_code: string;
  readonly lap_number: number;
  /** As in the session's laps; null for a lap F1 did not time. */
  readonly lap_time_ms: number | null;
  readonly compound: Compound | null;
  /**
   * The lap's four flags, as in the session's laps. Null is "not known":
   * the timing gave no value, or the index was built before it carried them.
   */
  readonly is_accurate: boolean | null;
  readonly is_deleted: boolean | null;
  readonly is_pit_in_lap: boolean | null;
  readonly is_pit_out_lap: boolean | null;
};

/** Why there is no comparison, in words for the page; `action` is anything more to add. */
export type TelemetryNotice = { readonly reason: string; readonly action?: string | null };

export type SessionTelemetry = {
  /** Every lap that has telemetry, driver by driver, as the index lists them. */
  readonly laps: TelemetryLapChoice[];
  /** The two laps compared when the tab opens; null when the session has fewer than two. */
  readonly pair: LapPair | null;
  /** The comparison of `pair`, or null with `notice` saying why there is none. */
  readonly comparison: TelemetryComparison | null;
  readonly notice: TelemetryNotice | null;
  /** The circuit's corner map, for the trace and the distance axis; null when the generation has none. */
  readonly corners: Corners | null;
};

/**
 * The index, and the comparison the tab opens on.
 *
 * If that first comparison cannot be loaded the tab still opens, with the
 * reason in `notice`: every other lap in the index is still there to compare.
 */
export async function readTelemetry(view: SessionView): Promise<SessionTelemetry> {
  requireListed(view, "telemetry");
  // The drivers are read here although only the comparison uses them: without
  // them a comparison fails, and the tab should say so before offering one.
  const [index, , corners] = await Promise.all([
    ARTIFACTS.telemetryIndex.read(view),
    ARTIFACTS.drivers.read(view),
    readIfListed(view, ARTIFACTS.corners)
  ]);
  const laps = telemetryLaps(index);
  const pair = defaultComparison(laps);
  if (!pair) {
    return {
      laps,
      pair: null,
      comparison: null,
      notice: { reason: "A comparison needs two laps with telemetry, and this session has fewer." },
      corners
    };
  }
  try {
    const result = await compareTelemetry(view, pair[0], pair[1]);
    return isTelemetryNotice(result)
      ? { laps, pair, comparison: null, notice: result, corners }
      : { laps, pair, comparison: result, notice: null, corners };
  } catch (error) {
    // The session is being opened again on another generation, and this tab
    // with it; that is not something to report inside the tab.
    if (isPublishedError(error, "generation_gone")) {
      throw error;
    }
    return {
      laps,
      pair,
      comparison: null,
      notice: {
        reason: `The telemetry of ${describe(pair[0])} and ${describe(pair[1])} could not be loaded.`,
        action: error instanceof Error ? error.message : null
      },
      corners
    };
  }
}

/**
 * Compare two laps. Reads the files of the two drivers, or of the one when
 * both laps are theirs; the index and the drivers it also needs are the ones
 * the tab already read, when the view shares its reads (`shareReads`).
 */
export async function compareTelemetry(
  view: SessionView,
  first: LapRef,
  second: LapRef
): Promise<TelemetryComparison | TelemetryNotice> {
  const [index, drivers] = await Promise.all([ARTIFACTS.telemetryIndex.read(view), ARTIFACTS.drivers.read(view)]);
  const a = listedLap(index, drivers, first);
  const b = listedLap(index, drivers, second);
  // Decided from the index, before either driver's file is asked for.
  if (!a || !b) {
    return { reason: "Telemetry is unavailable for one or both selected laps." };
  }
  const [fileA, fileB] = await Promise.all([readDriverTelemetry(view, a.entry), readDriverTelemetry(view, b.entry)]);
  const lapA = fileA.laps.find((lap) => lap.lap_number === first.lap);
  const lapB = fileB.laps.find((lap) => lap.lap_number === second.lap);
  if (!lapA || !lapB) {
    // The index and the files are one generation's, so this is a fault in
    // what was published and not something a reader can choose around.
    const missing = lapA ? second : first;
    return {
      reason: `The telemetry of ${describe(missing)} is listed for this session and is not in ${missing.driver}'s file.`
    };
  }
  return compareLaps({ meta: a.meta, lap: lapA }, { meta: b.meta, lap: lapB }, index.max_samples_per_lap);
}

/** One driver's telemetry, from the path the index gives for it. */
function readDriverTelemetry(view: SessionView, entry: Pick<TelemetryDriverEntry, "path">): Promise<DriverTelemetry> {
  return readRecord<"telemetry/{driver_code}.json">(view, entry.path, ["laps"]);
}

/** The laps of an index, one row for each: its drivers hold them as parallel arrays. */
export function telemetryLaps(index: TelemetryIndex): TelemetryLapChoice[] {
  return index.drivers.flatMap((entry) =>
    entry.lap_number.map((lap, position) => ({
      driver_code: entry.driver_code,
      lap_number: lap,
      lap_time_ms: entry.lap_time_ms[position] ?? null,
      compound: entry.compound[position] ?? null,
      is_accurate: flagAt(entry.is_accurate, position),
      is_deleted: flagAt(entry.is_deleted, position),
      is_pit_in_lap: flagAt(entry.is_pit_in_lap, position),
      is_pit_out_lap: flagAt(entry.is_pit_out_lap, position)
    }))
  );
}

/**
 * One lap's flag. Every index has the four arrays from pipeline version 8.
 * One published before that has none, and is still what is served for a
 * session until it is published again; its laps are then of unknown kind,
 * which is not the same as clean, and not the same as dirty either.
 */
function flagAt(flags: ReadonlyArray<boolean | null> | undefined, position: number): boolean | null {
  return flags?.[position] ?? null;
}

/**
 * Whether a lap is one to open a comparison on: timed accurately, not
 * deleted by the stewards, and neither into nor out of the pits.
 *
 * All four have to be known. A lap whose deletion or pit flag is null may be
 * a deleted lap or a pit lap for all the index says, and calling it clean
 * would be saying something nobody recorded.
 */
export function isCleanLap(lap: TelemetryLapChoice): boolean {
  return lap.is_accurate === true && lap.is_deleted === false && lap.is_pit_in_lap === false && lap.is_pit_out_lap === false;
}

/** What a lap menu says of a lap besides its time: "deleted", "pit in", "pit out". */
export function lapMarks(lap: TelemetryLapChoice): string[] {
  return [
    lap.is_deleted === true ? "deleted" : null,
    lap.is_pit_in_lap === true ? "pit in" : null,
    lap.is_pit_out_lap === true ? "pit out" : null
  ].filter((mark): mark is string => mark !== null);
}

type TimedLap = TelemetryLapChoice & { readonly lap_time_ms: number };

/**
 * The lap of a driver to offer first: their fastest clean lap, or failing
 * that their fastest lap of any kind, or failing that the first one listed.
 * Null for a driver with no lap in the index.
 */
export function preferredLap(laps: ReadonlyArray<TelemetryLapChoice>, driver: string): TelemetryLapChoice | null {
  const own = laps.filter((lap) => lap.driver_code === driver);
  const timed = own.filter((lap): lap is TimedLap => lap.lap_time_ms !== null && lap.lap_time_ms > 0);
  const fastestOf = (candidates: ReadonlyArray<TimedLap>) =>
    candidates.reduce<TimedLap | null>((best, lap) => (best === null || lap.lap_time_ms < best.lap_time_ms ? lap : best), null);
  return fastestOf(timed.filter(isCleanLap)) ?? fastestOf(timed) ?? own[0] ?? null;
}

/**
 * The laps a telemetry tab compares first: the preferred lap of each of the
 * two quickest drivers.
 *
 * A session's quickest lap on paper is often one that does not count: set
 * with a wheel over the line and deleted, or cut short through the pit
 * lane. So a driver is ranked by their fastest clean lap, and a driver who
 * has one comes before a driver who has none, whatever the times say.
 *
 * When no lap has a time to rank it by, it is the first lap listed of each of
 * the first two drivers, or the first two laps of the only one.
 */
export function defaultComparison(laps: ReadonlyArray<TelemetryLapChoice>): LapPair | null {
  const ranked = [...new Set(laps.map((lap) => lap.driver_code))]
    .map((driver) => preferredLap(laps, driver))
    .filter((lap): lap is TimedLap => lap !== null && lap.lap_time_ms !== null && lap.lap_time_ms > 0)
    .sort(
      (left, right) =>
        Number(isCleanLap(right)) - Number(isCleanLap(left)) ||
        left.lap_time_ms - right.lap_time_ms ||
        compareCodes(left.driver_code, right.driver_code)
    );
  if (ranked.length >= 2) {
    const [first, second] = ranked;
    return [
      { driver: first.driver_code, lap: first.lap_number },
      { driver: second.driver_code, lap: second.lap_number }
    ];
  }

  const first = laps[0];
  const second = laps.find((lap) => lap.driver_code !== first?.driver_code) ?? laps[1];
  if (!first || !second) {
    return null;
  }
  return [
    { driver: first.driver_code, lap: first.lap_number },
    { driver: second.driver_code, lap: second.lap_number }
  ];
}

/**
 * What the tab says of the laps it opened on. It says "clean" only of laps
 * that are known to be: where a driver has none, or the index does not say
 * what kind its laps are, the lap opened on is that driver's fastest of any
 * kind, and the page says so instead of passing it off as a clean one.
 */
export function openingNote(laps: ReadonlyArray<TelemetryLapChoice>, pair: LapPair | null): string | null {
  if (!pair) {
    return null;
  }
  const unclean = [...new Set(pair.filter((ref) => !isCleanLap(lapOf(laps, ref))).map((ref) => ref.driver))];
  if (unclean.length === 0) {
    return "It opens on the fastest clean lap of each of the two quickest drivers: timed accurately, not deleted, and not into or out of the pits.";
  }
  const who = unclean.length === 1 ? `${unclean[0]} has` : `${unclean.join(" and ")} have`;
  return `It opens on each driver's fastest lap. ${who} no lap known to be clean (timed accurately, not deleted, not into or out of the pits), so that is the fastest of any kind.`;
}

function lapOf(laps: ReadonlyArray<TelemetryLapChoice>, ref: LapRef): TelemetryLapChoice {
  return (
    laps.find((lap) => lap.driver_code === ref.driver && lap.lap_number === ref.lap) ?? {
      driver_code: ref.driver,
      lap_number: ref.lap,
      lap_time_ms: null,
      compound: null,
      is_accurate: null,
      is_deleted: null,
      is_pit_in_lap: null,
      is_pit_out_lap: null
    }
  );
}

export function isTelemetryNotice(value: TelemetryComparison | TelemetryNotice): value is TelemetryNotice {
  return "reason" in value;
}

/** A lap the index lists, with the driver's entry and what the comparison says of the lap. */
function listedLap(
  index: TelemetryIndex,
  drivers: ReadonlyArray<Driver>,
  ref: LapRef
): { entry: TelemetryDriverEntry; meta: ComparedLap } | null {
  const code = ref.driver.toUpperCase();
  const entry = index.drivers.find((item) => item.driver_code === code);
  const position = entry ? entry.lap_number.indexOf(ref.lap) : -1;
  if (!entry || position < 0) {
    return null;
  }
  return {
    entry,
    meta: {
      driver_code: code,
      team: drivers.find((driver) => driver.code === code)?.team?.name ?? null,
      lap_number: ref.lap,
      lap_time_ms: entry.lap_time_ms[position] ?? null,
      compound: entry.compound[position] ?? null
    }
  };
}

function describe(lap: LapRef): string {
  return `${lap.driver} lap ${lap.lap}`;
}

function compareCodes(left: string, right: string): number {
  if (left === right) {
    return 0;
  }
  return left < right ? -1 : 1;
}
