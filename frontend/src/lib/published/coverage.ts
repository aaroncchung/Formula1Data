import type { PointerCoverage, Shortfall } from "./types";

/**
 * The bars that are not about something missing. F1's car or position feed
 * arrived on time and sent the sample before again, for much of a lap: the
 * speed stands still, the lap's distance comes out wrong, and the car stops
 * on the map and jumps. Every figure of such a lap is there, and none of it
 * can be relied on, which "partial data" alone does not say.
 */
const REPEATS_BARS = new Set(["car_data_repeats", "position_repeats"]);

/**
 * The drivers whose telemetry a session's pointer says a feed repeated itself
 * for, in the order it names them and each once. Empty when it names none.
 */
export function driversWithRepeatingFeeds(coverage: PointerCoverage): string[] {
  const drivers: string[] = [];
  for (const shortfall of coverage.shortfalls) {
    if (REPEATS_BARS.has(shortfall.bar) && shortfall.driver !== null && !drivers.includes(shortfall.driver)) {
      drivers.push(shortfall.driver);
    }
  }
  return drivers;
}

/** The shortfalls under one bar, and who fell short of it, in a few words. */
export type ShortfallGroup = {
  readonly bar: string;
  /** The bar as words: "car data repeats". */
  readonly title: string;
  /** "22 drivers", "PER", "Whole session", or "Whole session and 2 drivers". */
  readonly who: string;
  /** In the pointer's order. */
  readonly entries: ReadonlyArray<Shortfall>;
};

/**
 * A pointer's shortfalls, one group for each bar, in the order the pointer
 * first names each bar. A session can fall short of one bar for every driver:
 * the 2026 Hungarian GP has 44 shortfalls under three bars, and the banner
 * above every tab listed each of them.
 */
export function shortfallGroups(coverage: PointerCoverage): ShortfallGroup[] {
  const byBar = new Map<string, Shortfall[]>();
  for (const shortfall of coverage.shortfalls) {
    byBar.set(shortfall.bar, [...(byBar.get(shortfall.bar) ?? []), shortfall]);
  }
  return [...byBar].map(([bar, entries]) => ({ bar, title: bar.replaceAll("_", " "), who: whoFellShort(entries), entries }));
}

function whoFellShort(entries: ReadonlyArray<Shortfall>): string {
  const drivers = [...new Set(entries.flatMap((entry) => (entry.driver === null ? [] : [entry.driver])))];
  const wholeSession = entries.some((entry) => entry.driver === null);
  if (drivers.length === 0) {
    return "Whole session";
  }
  const named = drivers.length === 1 ? (wholeSession ? "1 driver" : drivers[0]) : `${drivers.length} drivers`;
  return wholeSession ? `Whole session and ${named}` : named;
}
