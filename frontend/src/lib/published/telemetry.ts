/**
 * The telemetry tab's reads.
 *
 * A race has over a thousand telemetry laps, of about 100 kB each. The tab
 * reads the index that lists them when it opens, and after that only the two
 * laps being compared.
 *
 * The comparison itself is `telemetryCompare` in static-api-core.ts, which
 * was written for the build-time site and reads paths of the form
 * `sessions/<id>/<file>`. It is reused here unchanged through a reader that
 * maps those paths onto a pinned view, so that both sites align and thin two
 * laps the same way.
 */

import type { EmptyStateResponse, Lap, TelemetryComparison } from "../../types/domain";
import { ApiClientError, createStaticApi, isEmptyState } from "../static-api-core.ts";
import type { ArtifactReader, TelemetryIndex } from "../static-api-core.ts";
import { ARTIFACTS, requireListed } from "./artifacts.ts";
import type { SessionView } from "./client.ts";
import { isPublishedError } from "./errors.ts";

export type TelemetryLap = TelemetryIndex["laps"][number];

/** One lap of one driver. */
export type LapRef = { readonly driver: string; readonly lap: number };

export type LapPair = readonly [LapRef, LapRef];

export type SessionTelemetry = {
  /** Every lap that has telemetry, as the index lists them. */
  readonly laps: TelemetryLap[];
  /** The two laps compared when the tab opens; null when the session has fewer than two. */
  readonly pair: LapPair | null;
  /** The comparison of `pair`, or null with `notice` saying why there is none. */
  readonly comparison: TelemetryComparison | null;
  readonly notice: EmptyStateResponse | null;
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
  const [index, laps] = await Promise.all([
    ARTIFACTS.telemetryIndex.read(view),
    ARTIFACTS.laps.read(view),
    ARTIFACTS.drivers.read(view)
  ]);
  const pair = defaultComparison(index.laps, laps);
  if (!pair) {
    return {
      laps: index.laps,
      pair: null,
      comparison: null,
      notice: { reason: "A comparison needs two laps with telemetry, and this session has fewer." }
    };
  }
  try {
    const result = await compareTelemetry(view, pair[0], pair[1]);
    return isEmptyState(result)
      ? { laps: index.laps, pair, comparison: null, notice: result }
      : { laps: index.laps, pair, comparison: result, notice: null };
  } catch (error) {
    // The session is being opened again on another generation, and this tab
    // with it; that is not something to report inside the tab.
    if (isPublishedError(error, "generation_gone")) {
      throw error;
    }
    return {
      laps: index.laps,
      pair,
      comparison: null,
      notice: {
        reason: `The telemetry of ${describe(pair[0])} and ${describe(pair[1])} could not be loaded.`,
        action: error instanceof Error ? error.message : null
      }
    };
  }
}

/**
 * Compare two laps. Reads the two lap files; the index, the laps and the
 * drivers it also needs are the ones the tab already read, when the view
 * shares its reads (`shareReads`).
 */
export async function compareTelemetry(
  view: SessionView,
  first: LapRef,
  second: LapRef
): Promise<TelemetryComparison | EmptyStateResponse> {
  const sessionId = String(view.pointer.session_key);
  const result = await createStaticApi(staticReaderOver(view, sessionId)).telemetryCompare(
    sessionId,
    first.driver,
    first.lap,
    second.driver,
    second.lap
  );
  // The old reader's advice is for whoever runs the pipeline ("Generate
  // telemetry artifacts ..."), which a visitor to the site cannot do.
  return isEmptyState(result) ? { reason: result.reason } : result;
}

/**
 * The laps a telemetry tab compares first: the fastest lap of each of the two
 * drivers with the quickest laps.
 *
 * The old dashboard compared the first two entries of the index, which are
 * lap 1 for the first two drivers in alphabetical order: two standing starts.
 * When the lap times cannot rank the laps, that is still the fallback, with
 * the second lap taken from another driver where there is one.
 */
export function defaultComparison(
  indexed: ReadonlyArray<TelemetryLap>,
  laps: ReadonlyArray<Pick<Lap, "driver_code" | "lap_number" | "lap_time_ms" | "is_deleted">>
): LapPair | null {
  const withTelemetry = new Set(indexed.map((lap) => lapKey(lap.driver_code, lap.lap_number)));
  const fastest = new Map<string, { lap: number; time: number }>();
  for (const lap of laps) {
    const time = lap.lap_time_ms;
    if (typeof time !== "number" || time <= 0 || lap.is_deleted || !withTelemetry.has(lapKey(lap.driver_code, lap.lap_number))) {
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

  const first = indexed[0];
  const second = indexed.find((lap) => lap.driver_code !== first?.driver_code) ?? indexed[1];
  if (!first || !second) {
    return null;
  }
  return [
    { driver: first.driver_code, lap: first.lap_number },
    { driver: second.driver_code, lap: second.lap_number }
  ];
}

/**
 * A reader for `createStaticApi` over one pinned view. A path the generation
 * does not list becomes the old reader's "not found", which is the case it
 * already handles: a session without a telemetry index compares to an empty
 * state, not to a failure.
 */
function staticReaderOver(view: SessionView, sessionId: string): ArtifactReader {
  const prefix = `sessions/${sessionId}/`;
  return async <T>(path: string): Promise<T> => {
    // The catalog and the season files are not part of a session view.
    if (!path.startsWith(prefix)) {
      throw notFound(path);
    }
    try {
      return await view.read<T>(path.slice(prefix.length));
    } catch (error) {
      if (isPublishedError(error, "not_in_manifest")) {
        throw notFound(path);
      }
      throw error;
    }
  };
}

function notFound(path: string): ApiClientError {
  const message = `${path} is not part of this session's published data.`;
  return new ApiClientError(message, { code: "artifact_not_found", message, details: { path } }, "published");
}

function describe(lap: LapRef): string {
  return `${lap.driver} lap ${lap.lap}`;
}

function lapKey(driver: string, lap: number): string {
  return `${driver.toUpperCase()}/${lap}`;
}

function compareCodes(left: string, right: string): number {
  if (left === right) {
    return 0;
  }
  return left < right ? -1 : 1;
}
