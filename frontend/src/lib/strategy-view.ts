/**
 * How a session's pit stops and its strategy analysis are read for display.
 *
 * Four different lengths of time belong to a stop, and each is shown under
 * its own name:
 *
 * - stationary time, how long the car stood still, from F1's pit-stop feed;
 * - pit-lane time, also from that feed;
 * - entry to exit, the time between the timing's pit-entry and pit-exit
 *   times, which is the same stretch measured by another source;
 * - pit loss, what the stop cost against staying out, which the strategy
 *   analysis estimates from lap times and which needs an on-track baseline.
 *
 * F1's feed does not cover every stop, so a figure from it can be absent for
 * a stop the timing still has. `sources` in a stop says where each of its
 * figures came from; here the column a figure is in says the same.
 *
 * A car that was in the pit lane when the session was red-flagged is in the
 * stop list too (`under_red_flag`). What it has there is a wait for the
 * restart, 26 minutes in the 2026 Dutch GP, and not the length of a pit stop.
 * It is listed as that, and kept out of every figure that summarises stops.
 */

import type { PaceChangeAcrossStop, PitLossExclusion, PitStop, Strategy } from "./published/types.ts";

export type PitLossSummary =
  | {
      status: "estimated";
      estimate_ms: number;
      /** Robust spread of the qualifying stops; null when there are too few to have one. */
      spread_ms: number | null;
      qualifyingStopCount: number;
      stopCount: number;
    }
  /** Stops were recorded and too few of them qualify, so there is no figure. */
  | { status: "too_few_stops"; qualifyingStopCount: number; stopCount: number; minimumStopCount: number }
  | { status: "no_stops" }
  /** The generation has no strategy analysis. */
  | { status: "not_published" };

export function pitLossSummary(strategy: Strategy | null): PitLossSummary {
  if (!strategy) {
    return { status: "not_published" };
  }
  const pitLoss = strategy.pit_loss;
  if (pitLoss.estimate_ms !== null) {
    return {
      status: "estimated",
      estimate_ms: pitLoss.estimate_ms,
      spread_ms: pitLoss.spread_ms,
      qualifyingStopCount: pitLoss.qualifying_stop_count,
      stopCount: pitLoss.stop_count
    };
  }
  if (pitLoss.stop_count === 0) {
    return { status: "no_stops" };
  }
  return {
    status: "too_few_stops",
    qualifyingStopCount: pitLoss.qualifying_stop_count,
    stopCount: pitLoss.stop_count,
    minimumStopCount: pitLoss.minimum_stop_count
  };
}

export type PitLaneSummary = {
  median_ms: number | null;
  fastest_ms: number | null;
  slowest_ms: number | null;
  /** The stops the three figures are of: those with a time that were not a wait through a red flag. */
  timedStopCount: number;
  /** Every entry to the pit lane. */
  stopCount: number;
  /** Entries that were a wait through a red flag, which the figures leave out. */
  redFlagCount: number;
};

/**
 * Entry-to-exit times in summary. Taken from the strategy analysis when the
 * generation has one, and otherwise worked out from the stops the same way:
 * the median, so that one car held in the lane does not set the figure, and
 * without the cars that sat out a red flag there.
 */
export function pitLaneSummary(strategy: Strategy | null, stops: ReadonlyArray<PitStop>): PitLaneSummary {
  const redFlagCount = stops.filter((stop) => stop.under_red_flag).length;
  if (strategy) {
    const published = strategy.pit_lane_time;
    return {
      median_ms: published.median_ms,
      fastest_ms: published.fastest_ms,
      slowest_ms: published.slowest_ms,
      timedStopCount: published.timed_stop_count,
      stopCount: published.stop_count,
      redFlagCount
    };
  }
  const durations = measured(stops.filter((stop) => !stop.under_red_flag).map((stop) => stop.duration_ms));
  return {
    median_ms: median(durations),
    fastest_ms: durations.length ? durations[0] : null,
    slowest_ms: durations.length ? durations[durations.length - 1] : null,
    timedStopCount: durations.length,
    stopCount: stops.length,
    redFlagCount
  };
}

export type StationarySummary = {
  median_ms: number | null;
  /** The quickest stop of the session, and whose it was. */
  fastest: { driver_code: string; lap_number: number; stationary_ms: number } | null;
  /** Stops F1's pit-stop feed gives a stationary time for, not counting waits through a red flag. */
  timedStopCount: number;
  /** Every entry to the pit lane that was not a wait through a red flag. */
  stopCount: number;
};

/**
 * How long cars stood still, over the stops F1's pit-stop feed reports. A car
 * that sat out a red flag in the pit lane was not making a pit stop, and is
 * not counted among them.
 */
export function stationarySummary(stops: ReadonlyArray<PitStop>): StationarySummary {
  const racing = stops.filter((stop) => !stop.under_red_flag);
  let fastest: StationarySummary["fastest"] = null;
  for (const stop of racing) {
    if (stop.stationary_ms !== null && (fastest === null || stop.stationary_ms < fastest.stationary_ms)) {
      fastest = { driver_code: stop.driver_code, lap_number: stop.lap_number, stationary_ms: stop.stationary_ms };
    }
  }
  const times = measured(racing.map((stop) => stop.stationary_ms));
  return { median_ms: median(times), fastest, timedStopCount: times.length, stopCount: racing.length };
}

export type StopPitLoss =
  | { status: "estimated"; pit_loss_ms: number }
  /** `reason` is the publisher's code; `pitLossExclusionLabel` words it. */
  | { status: "excluded"; reason: PitLossExclusion };

export type PitStopLogRow = {
  driver_code: string;
  lap_number: number;
  /** When the car crossed the pit entry, on the session clock; null for a stop only F1's feed reports. */
  entry_time_ms: number | null;
  /** From F1's pit-stop feed; null for a stop it does not report. */
  stationary_ms: number | null;
  /** From F1's pit-stop feed; null for a stop it does not report. */
  pit_lane_ms: number | null;
  /** From the timing; null when the car did not come back out. */
  duration_ms: number | null;
  /**
   * The session was red-flagged while the car was in the pit lane. Its times
   * are then a wait for the restart, and are shown as one and not as a stop's.
   */
  under_red_flag: boolean;
  /** Null when the generation has no strategy analysis, or the analysis does not mention the stop. */
  pitLoss: StopPitLoss | null;
};

/** Every stop, with the pit loss the estimate gave it or the reason it gave none. */
export function pitStopLog(strategy: Strategy | null, pitStops: ReadonlyArray<PitStop>): PitStopLogRow[] {
  const lossByStop = new Map<string, StopPitLoss>();
  for (const stop of strategy?.pit_loss.stops ?? []) {
    if (stop.driver_code === null || stop.lap_number === null) {
      continue;
    }
    const key = stopKey(stop.driver_code, stop.lap_number);
    if (stop.pit_loss_ms !== null) {
      lossByStop.set(key, { status: "estimated", pit_loss_ms: stop.pit_loss_ms });
    } else if (stop.excluded_reason !== null) {
      lossByStop.set(key, { status: "excluded", reason: stop.excluded_reason });
    }
  }
  return pitStops.map((stop) => ({
    driver_code: stop.driver_code,
    lap_number: stop.lap_number,
    entry_time_ms: stop.entry_time_ms,
    stationary_ms: stop.stationary_ms,
    pit_lane_ms: stop.pit_lane_ms,
    duration_ms: stop.duration_ms,
    under_red_flag: stop.under_red_flag,
    pitLoss: lossByStop.get(stopKey(stop.driver_code, stop.lap_number)) ?? null
  }));
}

// Every reason the schema lists, in words short enough for a table cell. A
// reason the format gains has no entry here and stops this compiling.
const PIT_LOSS_EXCLUSIONS: Readonly<Record<PitLossExclusion, string>> = {
  no_lap_number: "no lap number",
  missing_lap_time: "no in-lap or out-lap time",
  first_lap: "stopped on lap 1",
  back_to_back_stops: "stops on consecutive laps",
  not_green: "not under green",
  too_few_baseline_laps: "too few clean laps around it"
};

export function pitLossExclusionLabel(reason: PitLossExclusion): string {
  return PIT_LOSS_EXCLUSIONS[reason];
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
export function paceChange(estimate: Pick<PaceChangeAcrossStop, "first_clean_lap_gain_ms">): PaceChange {
  const gain = estimate.first_clean_lap_gain_ms;
  if (gain === null) {
    return { direction: "none", change_ms: null, text: "--" };
  }
  if (gain === 0) {
    return { direction: "level", change_ms: 0, text: "No change" };
  }
  const change = Math.abs(gain);
  const direction = gain > 0 ? "quicker" : "slower";
  return { direction, change_ms: change, text: `${(change / 1000).toFixed(3)}s ${direction}` };
}

function stopKey(driver: string, lap: number): string {
  return `${driver.toUpperCase()}/${lap}`;
}

/** The values that are there, smallest first. */
function measured(values: ReadonlyArray<number | null>): number[] {
  return values.filter((value): value is number => value !== null).sort((left, right) => left - right);
}

function median(sorted: ReadonlyArray<number>): number | null {
  if (sorted.length === 0) {
    return null;
  }
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
