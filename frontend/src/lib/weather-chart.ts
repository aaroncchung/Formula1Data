/**
 * The data behind the weather chart.
 *
 * The chart is drawn against the session clock, which every sample carries
 * as `time_ms`. In a race or sprint a sample also says which lap the leader
 * was on, and that is shown beside the time; it is not the axis, because the
 * samples before the start and after the flag have no lap, and no other kind
 * of session has laps to count at all.
 *
 * Any reading of a sample can be missing: F1's feed sometimes leaves a sensor
 * out, and the format then has null for it. A missing temperature is a break
 * in its line, and a sample that does not say whether it was raining is
 * counted as that. Neither is ever drawn or described as zero degrees or as
 * dry weather.
 */

import type { WeatherSample } from "./published/types.ts";

export type WeatherPoint = {
  /** Milliseconds on the session clock, which starts with F1's timing feed. */
  time_ms: number;
  /** The lap the leader was on; null outside a race's running and in any other session. */
  lap_number: number | null;
  air_temp_c: number | null;
  track_temp_c: number | null;
  humidity_pct: number | null;
  wind_speed_kph: number | null;
  /** Null when the sample does not say. */
  rainfall: boolean | null;
};

export type WeatherPlot = {
  /** Every sample, earliest first. */
  points: WeatherPoint[];
  /** Samples taken while it was raining. */
  rainCount: number;
  /** Samples that say whether it was raining, one way or the other. */
  rainKnownCount: number;
  /** Samples that have each of the two readings the chart draws. */
  airCount: number;
  trackCount: number;
};

export function weatherPlot(samples: ReadonlyArray<WeatherSample>): WeatherPlot {
  const points = samples
    .map((sample) => ({
      time_ms: sample.time_ms,
      lap_number: sample.lap_number,
      air_temp_c: sample.air_temp_c,
      track_temp_c: sample.track_temp_c,
      humidity_pct: sample.humidity_pct,
      wind_speed_kph: sample.wind_speed_kph,
      rainfall: sample.rainfall
    }))
    .sort((left, right) => left.time_ms - right.time_ms);
  return {
    points,
    rainCount: points.filter((point) => point.rainfall === true).length,
    rainKnownCount: points.filter((point) => point.rainfall !== null).length,
    airCount: points.filter((point) => point.air_temp_c !== null).length,
    trackCount: points.filter((point) => point.track_temp_c !== null).length
  };
}

/** Whether the plot has a temperature to draw at all. */
export function hasTemperatures(plot: WeatherPlot): boolean {
  return plot.airCount > 0 || plot.trackCount > 0;
}

/** What is in the chart and what is not, in a few sentences. */
export function describeWeatherPlot(plot: WeatherPlot): string {
  const total = plot.points.length;
  if (total === 0) {
    return "No weather samples in this session.";
  }
  const sentences = [`${count(total, "sample")}.`];

  const withoutAir = total - plot.airCount;
  const withoutTrack = total - plot.trackCount;
  if (!hasTemperatures(plot)) {
    sentences.push("None has an air or a track temperature.");
  } else if (withoutAir > 0 || withoutTrack > 0) {
    const missing = [
      withoutAir > 0 ? `${withoutAir} without an air temperature` : null,
      withoutTrack > 0 ? `${withoutTrack} without a track temperature` : null
    ].filter((part): part is string => part !== null);
    sentences.push(`${missing.join(" and ")}: the line breaks there.`);
  }

  // A sample that does not say whether it was raining is not a dry sample.
  const unknown = total - plot.rainKnownCount;
  if (plot.rainKnownCount === 0) {
    sentences.push(total === 1 ? "It does not say whether it was raining." : "None says whether it was raining.");
  } else {
    const among = unknown === 0 ? count(total, "sample") : `the ${plot.rainKnownCount} that say`;
    sentences.push(
      plot.rainCount === 0
        ? unknown === 0
          ? "No rain was recorded."
          : `No rain was recorded in ${among}.`
        : `Rain was recorded in ${plot.rainCount} of ${among}.`
    );
    if (unknown > 0) {
      sentences.push(`${unknown} ${unknown === 1 ? "does" : "do"} not say whether it was raining.`);
    }
  }
  return sentences.join(" ");
}

/**
 * What a chart adds to the time of the sample under the pointer: the lap the
 * leader was on, and whether it was raining, each only if the sample says.
 * " · lap 34 · raining", or nothing at all.
 */
export function sampleNote(plot: WeatherPlot, timeMs: number): string {
  const point = plot.points.find((item) => item.time_ms === timeMs);
  if (!point) {
    return "";
  }
  const parts = [
    point.lap_number === null ? null : `lap ${point.lap_number}`,
    point.rainfall === null ? null : point.rainfall ? "raining" : "dry"
  ].filter((part): part is string => part !== null);
  return parts.map((part) => ` · ${part}`).join("");
}

const MS_PER_MINUTE = 60_000;
// Round numbers of minutes a person reads on a clock, smallest first.
const TICK_STEPS_MINUTES = [1, 2, 5, 10, 15, 20, 30, 60, 120];

/**
 * Where to put the marks on a session-clock axis: on whole multiples of a
 * round number of minutes. Left to itself a chart picks round numbers of
 * milliseconds, which land on times like 0:33:20.
 */
export function sessionClockTicks(fromMs: number, toMs: number, atMost = 8): number[] {
  if (!Number.isFinite(fromMs) || !Number.isFinite(toMs) || toMs <= fromMs) {
    return [];
  }
  const limit = Math.max(atMost, 1);
  const fits = (minutes: number) => Math.floor(toMs / (minutes * MS_PER_MINUTE)) - Math.ceil(fromMs / (minutes * MS_PER_MINUTE)) + 1 <= limit;
  const stepMinutes = TICK_STEPS_MINUTES.find(fits) ?? TICK_STEPS_MINUTES[TICK_STEPS_MINUTES.length - 1];
  const step = stepMinutes * MS_PER_MINUTE;
  const ticks: number[] = [];
  for (let tick = Math.ceil(fromMs / step) * step; tick <= toMs; tick += step) {
    ticks.push(tick);
  }
  return ticks;
}

function count(value: number, noun: string): string {
  return `${value} ${noun}${value === 1 ? "" : "s"}`;
}
