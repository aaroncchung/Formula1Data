import type { Lap } from "@/types/domain";

/**
 * Each driver's fastest lap, quickest driver first.
 *
 * A deleted lap does not count: it was set outside track limits and is not
 * the driver's time. A driver with no timed lap left is not listed.
 */
export function fastestLapByDriver(laps: ReadonlyArray<Lap>): Lap[] {
  const fastest = new Map<string, Lap & { lap_time_ms: number }>();
  for (const lap of laps) {
    const time = lap.lap_time_ms;
    if (typeof time !== "number" || !Number.isFinite(time) || time <= 0 || lap.is_deleted) {
      continue;
    }
    const best = fastest.get(lap.driver_code);
    // Of two equal laps the one set first is the driver's fastest lap,
    // whatever order the laps are listed in.
    if (!best || time < best.lap_time_ms || (time === best.lap_time_ms && lap.lap_number < best.lap_number)) {
      fastest.set(lap.driver_code, { ...lap, lap_time_ms: time });
    }
  }
  return [...fastest.values()].sort(
    (left, right) => left.lap_time_ms - right.lap_time_ms || compareCodes(left.driver_code, right.driver_code)
  );
}

function compareCodes(left: string, right: string): number {
  if (left === right) {
    return 0;
  }
  return left < right ? -1 : 1;
}
