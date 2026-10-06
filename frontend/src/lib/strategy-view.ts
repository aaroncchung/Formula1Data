/**
 * How the strategy analysis is read for display.
 *
 * Two different quantities used to share one label. Pit-lane time is the
 * transit from pit entry to pit exit. Pit loss is what a stop costs against
 * staying out, and needs an on-track baseline. The artifact now reports both
 * under their own names (`calculate_strategy` in
 * backend/app/analysis/strategy.py); a generation built before that carries
 * the mean pit-lane time in `pit_loss_estimate_ms`, which is not shown as a
 * pit loss here.
 */

import type { PitStop, StrategyEstimate, StrategyResult } from "@/types/domain";
import { parsePandasDuration } from "./pandas-time.ts";

export type PitLossSummary =
  | {
      status: "estimated";
      estimate_ms: number;
      /** Robust spread of the qualifying stops; null when it was not published. */
      spread_ms: number | null;
      qualifyingStopCount: number;
      stopCount: number;
    }
  /** Stops were recorded and too few of them qualify, so there is no figure. */
  | { status: "too_few_stops"; qualifyingStopCount: number; stopCount: number; minimumStopCount: number | null }
  | { status: "no_stops" }
  /** The generation has no pit-loss estimate: built before there was one, or no strategy artifact. */
  | { status: "not_published" };

export function pitLossSummary(strategy: StrategyResult | null): PitLossSummary {
  const pitLoss = strategy?.pit_loss;
  // Decided by the `pit_loss` object and not by `pit_loss_estimate_ms`, which
  // older generations fill with something else.
  if (!pitLoss) {
    return { status: "not_published" };
  }
  const qualifyingStopCount = count(pitLoss.qualifying_stop_count);
  const stopCount = count(pitLoss.stop_count);
  if (isMeasured(pitLoss.estimate_ms)) {
    return {
      status: "estimated",
      estimate_ms: pitLoss.estimate_ms,
      spread_ms: isMeasured(pitLoss.spread_ms) ? pitLoss.spread_ms : null,
      qualifyingStopCount,
      stopCount
    };
  }
  if (stopCount === 0) {
    return { status: "no_stops" };
  }
  return {
    status: "too_few_stops",
    qualifyingStopCount,
    stopCount,
    minimumStopCount: isMeasured(pitLoss.minimum_stop_count) ? pitLoss.minimum_stop_count : null
  };
}

export type PitLaneSummary = {
  median_ms: number | null;
  fastest_ms: number | null;
  slowest_ms: number | null;
  timedStopCount: number;
  stopCount: number;
};

/**
 * Pit-lane transit times in summary. Taken from the artifact when it has
 * them, and otherwise worked out from the stops the same way
 * (`_pit_lane_time`): the median, so that one car held in the lane does not
 * set the figure.
 */
export function pitLaneSummary(strategy: StrategyResult | null, stops: ReadonlyArray<PitStop>): PitLaneSummary {
  const published = strategy?.pit_lane_time;
  if (published) {
    return {
      median_ms: isMeasured(published.median_ms) ? published.median_ms : null,
      fastest_ms: isMeasured(published.fastest_ms) ? published.fastest_ms : null,
      slowest_ms: isMeasured(published.slowest_ms) ? published.slowest_ms : null,
      timedStopCount: count(published.timed_stop_count),
      stopCount: count(published.stop_count)
    };
  }
  const durations = stops
    .map((stop) => stop.duration_ms)
    .filter(isMeasured)
    .sort((left, right) => left - right);
  return {
    median_ms: median(durations),
    fastest_ms: durations.length ? durations[0] : null,
    slowest_ms: durations.length ? durations[durations.length - 1] : null,
    timedStopCount: durations.length,
    stopCount: stops.length
  };
}

export type StopPitLoss =
  | { status: "estimated"; pit_loss_ms: number }
  /** `reason` is the publisher's code; `pitLossExclusionLabel` words it. */
  | { status: "excluded"; reason: string };

export type PitStopLogRow = {
  driver_code: string;
  lap_number: number;
  /** Pit-lane transit; null when the source had no pit-exit time to pair. */
  duration_ms: number | null;
  /** When the car entered the pit lane, in milliseconds on the session clock. */
  entry_clock_ms: number | null;
  /** Null when the generation has no per-stop pit loss. */
  pitLoss: StopPitLoss | null;
};

/** Every stop, with the pit loss the estimate gave it or the reason it gave none. */
export function pitStopLog(strategy: StrategyResult | null, pitStops: ReadonlyArray<PitStop>): PitStopLogRow[] {
  const stops = strategy?.pit_stops?.length ? strategy.pit_stops : pitStops;
  const lossByStop = new Map<string, StopPitLoss>();
  for (const stop of strategy?.pit_loss?.stops ?? []) {
    const key = stopKey(stop.driver_code, stop.lap_number);
    if (key === null) {
      continue;
    }
    if (isMeasured(stop.pit_loss_ms)) {
      lossByStop.set(key, { status: "estimated", pit_loss_ms: stop.pit_loss_ms });
    } else if (stop.excluded_reason) {
      lossByStop.set(key, { status: "excluded", reason: stop.excluded_reason });
    }
  }
  return stops.map((stop) => ({
    driver_code: stop.driver_code,
    lap_number: stop.lap_number,
    duration_ms: isMeasured(stop.duration_ms) ? stop.duration_ms : null,
    entry_clock_ms: parsePandasDuration(stop.local_time),
    pitLoss: lossByStop.get(stopKey(stop.driver_code, stop.lap_number) ?? "") ?? null
  }));
}

// The reasons a stop is left out of the pit-loss estimate, as the publisher
// codes them (`_PIT_LOSS_EXCLUSIONS`), in words short enough for a table cell.
const PIT_LOSS_EXCLUSIONS: Readonly<Record<string, string>> = {
  no_lap_number: "no lap number",
  missing_lap_time: "no in-lap or out-lap time",
  first_lap: "stopped on lap 1",
  back_to_back_stops: "stops on consecutive laps",
  not_green: "not under green",
  too_few_baseline_laps: "too few clean laps around it"
};

export function pitLossExclusionLabel(reason: string): string {
  return PIT_LOSS_EXCLUSIONS[reason] ?? reason.replaceAll("_", " ");
}

export type PaceChange =
  /** `change_ms` is how much, always positive; `direction` is which way. */
  | { direction: "quicker" | "slower"; change_ms: number; text: string }
  | { direction: "level"; change_ms: 0; text: string }
  /** No pair of laps to compare; the row's own caveat says why. */
  | { direction: "none"; change_ms: null; text: string };

/**
 * The pace change across a stop, in words.
 *
 * The artifact's figure is the lap before minus the lap after, so positive is
 * quicker on the new tyres. A signed number invites reading it the other way,
 * as this page once did ("negative is quicker"), so the direction is spelled
 * out and the number shown without a sign.
 */
export function paceChange(estimate: Pick<StrategyEstimate, "first_clean_lap_gain_ms">): PaceChange {
  const gain = estimate.first_clean_lap_gain_ms;
  if (!isMeasured(gain)) {
    return { direction: "none", change_ms: null, text: "--" };
  }
  if (gain === 0) {
    return { direction: "level", change_ms: 0, text: "No change" };
  }
  const change = Math.abs(gain);
  const direction = gain > 0 ? "quicker" : "slower";
  return { direction, change_ms: change, text: `${(change / 1000).toFixed(3)}s ${direction}` };
}

function stopKey(driver: string | null | undefined, lap: number | null | undefined): string | null {
  return driver && isMeasured(lap) ? `${driver.toUpperCase()}/${lap}` : null;
}

function median(sorted: ReadonlyArray<number>): number | null {
  if (sorted.length === 0) {
    return null;
  }
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function count(value: number | null | undefined): number {
  return isMeasured(value) ? value : 0;
}

function isMeasured(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
