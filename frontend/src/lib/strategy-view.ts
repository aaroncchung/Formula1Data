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
 *
 * And the stop list is every entry to the pit lane, of which not every one is
 * a pit stop. In the 2025 Canadian GP the field followed the safety car down
 * the pit lane three times in the last four laps: 49 of that race's 82
 * entries, which this page counted as pit stops. `pitEntryKind` says what an
 * entry was, and only a stop is counted as one.
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

/**
 * What an entry to the pit lane was, as far as F1's feeds say.
 *
 * - `stop`: F1's pit-stop feed gives it a stationary time, or its tyre data
 *   has the car on another set afterwards. Either is word that the car
 *   stopped; the feed leaves out about one stop in eleven.
 * - `passage`: neither, and the tyre data has the car on the same set
 *   afterwards. A drive-through penalty, or the field led down the pit lane
 *   by the safety car.
 * - `red_flag_wait`: the session was red-flagged while the car was there.
 * - `not_known`: none of that can be said. The car did not come out again, or
 *   F1 sent no tyre data for it.
 */
export type PitEntryKind = "stop" | "passage" | "red_flag_wait" | "not_known";

export function pitEntryKind(entry: Pick<PitStop, "under_red_flag" | "stationary_ms" | "tyres_changed">): PitEntryKind {
  if (entry.under_red_flag) {
    return "red_flag_wait";
  }
  if (entry.stationary_ms !== null || entry.tyres_changed === true) {
    return "stop";
  }
  // Compared with false and not tested for truth: a generation from before
  // the stop list said anything of the tyres has nothing here, which is not
  // word that the car kept them.
  return entry.tyres_changed === false ? "passage" : "not_known";
}

export type PitEntryCounts = {
  /** Every entry to the pit lane. The four below add up to it. */
  entries: number;
  stops: number;
  passages: number;
  redFlagWaits: number;
  notKnown: number;
  /** How many drivers made at least one stop. */
  driversWhoStopped: number;
};

export function pitEntryCounts(entries: ReadonlyArray<PitStop>): PitEntryCounts {
  const counts: PitEntryCounts = { entries: entries.length, stops: 0, passages: 0, redFlagWaits: 0, notKnown: 0, driversWhoStopped: 0 };
  const stopped = new Set<string>();
  for (const entry of entries) {
    const kind = pitEntryKind(entry);
    if (kind === "stop") {
      counts.stops += 1;
      stopped.add(entry.driver_code);
    } else if (kind === "passage") {
      counts.passages += 1;
    } else if (kind === "red_flag_wait") {
      counts.redFlagWaits += 1;
    } else {
      counts.notKnown += 1;
    }
  }
  counts.driversWhoStopped = stopped.size;
  return counts;
}

/** The entries to the pit lane that were not pit stops, in words, or nothing when every one was. */
export function otherEntriesNote(counts: PitEntryCounts): string {
  const parts = [
    counts.passages > 0 ? `${counts.passages} went through without stopping` : "",
    counts.redFlagWaits > 0 ? `${counts.redFlagWaits} waited through a red flag` : "",
    counts.notKnown > 0 ? `${counts.notKnown} F1's data does not say enough of` : ""
  ].filter(Boolean);
  const others = counts.entries - counts.stops;
  return others > 0 ? `${others} other ${others === 1 ? "entry" : "entries"} to the pit lane: ${parts.join(", ")}` : "";
}

export type CompoundUsage = {
  /** Stints by compound, most used first, for the compounds F1 named. */
  named: Array<[string, number]>;
  /** Stints F1 named no compound for. Not a compound: it could be any of the ones above. */
  unnamedStints: number;
};

// The key the strategy analysis counts stints with no compound under.
const UNNAMED_COMPOUND = "UNKNOWN";

/**
 * The compounds a session was run on. The analysis counts the stints F1 named
 * no compound for under their own key, which is not a compound: the 2025
 * Miami GP was run on two, and with that key counted the page said three.
 */
export function compoundUsage(strategy: Strategy | null): CompoundUsage {
  const usage = Object.entries(strategy?.compound_usage ?? {});
  return {
    named: usage.filter(([compound]) => compound !== UNNAMED_COMPOUND).sort((a, b) => b[1] - a[1]),
    unnamedStints: usage.find(([compound]) => compound === UNNAMED_COMPOUND)?.[1] ?? 0
  };
}

export type PitLaneSummary = {
  median_ms: number | null;
  fastest_ms: number | null;
  slowest_ms: number | null;
  /**
   * The stops the three figures are of: those F1's pit-stop feed reports,
   * that have a time and were not a wait through a red flag.
   */
  timedStopCount: number;
  /** Every entry to the pit lane. */
  stopCount: number;
  /** Entries that were a wait through a red flag, which the figures leave out. */
  redFlagCount: number;
};

/**
 * Entry-to-exit times in summary. Taken from the strategy analysis when the
 * generation has one, and otherwise worked out from the stops the same way:
 * over the stops F1's pit-stop feed reports, since the time a car took to
 * drive through is not the time of a stop; the median, so that one car held
 * in the lane does not set the figure; and without the cars that sat out a
 * red flag there.
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
  const durations = measured(
    stops.filter((stop) => !stop.under_red_flag && stop.stationary_ms !== null).map((stop) => stop.duration_ms)
  );
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
  /** Every stop: those, and the ones the feed leaves out that F1's tyre data shows. */
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
  return { median_ms: median(times), fastest, timedStopCount: times.length, stopCount: pitEntryCounts(stops).stops };
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
  /** What the entry was: a stop, or a car going through, or waiting. */
  kind: PitEntryKind;
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
    kind: pitEntryKind(stop),
    pitLoss: lossByStop.get(stopKey(stop.driver_code, stop.lap_number)) ?? null
  }));
}

// Every reason the schema lists, in words short enough for a table cell. A
// reason the format gains has no entry here and stops this compiling.
const PIT_LOSS_EXCLUSIONS: Readonly<Record<PitLossExclusion, string>> = {
  no_lap_number: "no lap number",
  red_flag_wait: "waited through a red flag",
  no_stop: "went through without stopping",
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
