/**
 * The artifacts a page reads from a pinned view, by name and by type.
 *
 * One reader for each thing a tab shows, so that a tab asks for exactly its
 * own files when it is first opened (AR-07). The contents are still in the
 * site's existing format, hence the existing types; step 3 of the rewrite
 * replaces these with generated ones.
 */

import type { ChartSeries, Driver, Result } from "../../types/domain";
import type { SessionView } from "./client.ts";
import { PublishedDataError } from "./errors.ts";

export const RESULTS_PATH = "results.json";
export const DRIVERS_PATH = "drivers.json";
export const LAP_TIMES_PATH = "analysis/lap-times.json";

export type SessionResults = {
  readonly results: Result[];
  readonly drivers: Driver[];
};

/** The classification, with the drivers it needs for names, teams and colours. */
export async function readResults(view: SessionView): Promise<SessionResults> {
  const [results, drivers] = await Promise.all([
    readList<Result>(view, RESULTS_PATH),
    readList<Driver>(view, DRIVERS_PATH)
  ]);
  return { results, drivers };
}

export type SessionLapTimes = {
  readonly series: ChartSeries[];
  readonly drivers: Driver[];
};

/**
 * One lap-time series for each driver, with the drivers the chart styles them
 * from: team-mates share a colour, and the driver list is what tells the two
 * lines apart (lib/driver-style.ts).
 */
export async function readLapTimes(view: SessionView): Promise<SessionLapTimes> {
  // One after the other on purpose. A generation without lap times then fails
  // before anything is requested, and the drivers are normally in the HTTP
  // cache already, because the results tab reads them and opens first.
  const series = await readList<ChartSeries>(view, LAP_TIMES_PATH);
  const drivers = await readList<Driver>(view, DRIVERS_PATH);
  return { series, drivers };
}

/**
 * Read an artifact that is a list. Only that much is checked: a component
 * that maps over an object takes the whole page down, while the shape of each
 * row is vouched for by the manifest's format version (rule 7).
 */
async function readList<T>(view: SessionView, path: string): Promise<T[]> {
  const payload = await view.read<unknown>(path);
  if (!Array.isArray(payload)) {
    throw new PublishedDataError("invalid_artifact", `${path} is not a list.`, { path });
  }
  const rows: unknown[] = payload;
  return rows as T[];
}
