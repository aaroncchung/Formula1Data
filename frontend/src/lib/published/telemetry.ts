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
 * The index says everything a lap is chosen by: its time and its compound.
 * The laps of the session are not read here.
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
      compound: entry.compound[position] ?? null
    }))
  );
}

/**
 * The laps a telemetry tab compares first: the fastest lap of each of the two
 * drivers with the quickest laps.
 *
 * When no lap has a time to rank it by, it is the first lap listed of each of
 * the first two drivers, or the first two laps of the only one.
 */
export function defaultComparison(laps: ReadonlyArray<TelemetryLapChoice>): LapPair | null {
  const fastest = new Map<string, { lap: number; time: number }>();
  for (const lap of laps) {
    const time = lap.lap_time_ms;
    if (time === null || time <= 0) {
      continue;
    }
    const best = fastest.get(lap.driver_code);
    if (!best || time < best.time) {
      fastest.set(lap.driver_code, { lap: lap.lap_number, time });
    }
  }
  const ranked = [...fastest.entries()].sort(
    ([leftDriver, left], [rightDriver, right]) => left.time - right.time || compareCodes(leftDriver, rightDriver)
  );
  if (ranked.length >= 2) {
    const [[firstDriver, first], [secondDriver, second]] = ranked;
    return [
      { driver: firstDriver, lap: first.lap },
      { driver: secondDriver, lap: second.lap }
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
