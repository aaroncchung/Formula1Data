/**
 * What the classification's time column says for each driver.
 *
 * The artifact has one field for it, `gap`, taken from FastF1's `Time`, and
 * that field means three different things: the winner's race time, the gap to
 * the winner for a driver on the lead lap, and for a lapped driver how long
 * after the winner they took the flag. The last is not a gap to anyone. In
 * the 2026 Austrian GP it puts Lawson, a lap down in ninth, at 15.3 s, ahead
 * of Leclerc's 45.7 s in eighth on the lead lap. A lapped driver is therefore
 * shown as laps down, which is how a classification is written.
 */

import type { Result } from "@/types/domain";
import { formatDuration, formatElapsed, parsePandasDuration } from "./pandas-time.ts";

/** The laps the winner completed, or null when the classification does not say. */
export function leaderLapCount(results: ReadonlyArray<Result>): number | null {
  const winner = results.find((row) => row.position === 1);
  const laps = winner?.laps ?? null;
  return typeof laps === "number" && Number.isFinite(laps) ? laps : null;
}

export function formatResultGap(result: Result, leaderLaps: number | null): string {
  const time = parsePandasDuration(result.gap);
  if (result.position === 1) {
    return time === null ? "Winner" : formatDuration(time);
  }
  const lapsDown = lapsBehind(result, leaderLaps);
  // A retirement is also short of laps, but it has no time and its status
  // already says why; "laps down" is only for a car that was still running.
  if (lapsDown > 0 && (time !== null || /lap/i.test(result.status ?? ""))) {
    return `+${lapsDown} ${lapsDown === 1 ? "lap" : "laps"}`;
  }
  if (time !== null) {
    return `+${formatElapsed(time)}`;
  }
  const text = result.gap?.trim() ?? "";
  // Whatever else a source wrote here, such as "+1 Lap", is passed on as it
  // is. pandas' own word for "no value" is not.
  return text === "" || text === "NaT" || text === "None" ? "--" : text;
}

function lapsBehind(result: Result, leaderLaps: number | null): number {
  if (leaderLaps === null || typeof result.laps !== "number" || !Number.isFinite(result.laps)) {
    return 0;
  }
  return Math.max(0, leaderLaps - result.laps);
}
