import type { PointerCoverage } from "./types";

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
