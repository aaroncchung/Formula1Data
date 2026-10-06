/**
 * The data behind the weather chart.
 *
 * The chart is drawn against the session clock, which every sample carries
 * as `time_ms`. In a race or sprint a sample also says which lap the leader
 * was on, and that is shown beside the time; it is not the axis, because the
 * samples before the start and after the flag have no lap, and no other kind
 * of session has laps to count at all.
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
  rainfall: boolean;
};

export type WeatherPlot = {
  /** Every sample, earliest first. */
  points: WeatherPoint[];
  /** Samples taken while it was raining. */
  rainCount: number;
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
  return { points, rainCount: points.filter((point) => point.rainfall).length };
}

/** What is in the chart, in a sentence or two. */
export function describeWeatherPlot(plot: WeatherPlot): string {
  const total = plot.points.length;
  if (total === 0) {
    return "No weather samples in this session.";
  }
  return [
    `${count(total, "sample")}.`,
    plot.rainCount === 0 ? "No rain was recorded." : `Rain was recorded in ${plot.rainCount} of ${count(total, "sample")}.`
  ].join(" ");
}

/** "Session clock 1:22:52 · lap 34" is built from this: the lap of the sample taken at a time, if it has one. */
export function lapAt(plot: WeatherPlot, timeMs: number): number | null {
  return plot.points.find((point) => point.time_ms === timeMs)?.lap_number ?? null;
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
