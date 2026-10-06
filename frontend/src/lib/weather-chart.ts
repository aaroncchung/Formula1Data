/**
 * The data behind the weather chart.
 *
 * The chart is drawn against the session clock. Its X axis used to be
 * `lap_number`, which is null in every weather sample that has been published
 * (AR-12), so every point sat at the same place. A sample does carry the time
 * it was taken at, as a pandas duration, and that is what places it.
 */

import type { WeatherSample } from "@/types/domain";
import { parsePandasDuration } from "./pandas-time.ts";

export type WeatherPoint = {
  /** Milliseconds on the session clock, which starts with F1's timing feed. */
  time_ms: number;
  air_temp_c: number | null;
  track_temp_c: number | null;
  humidity_pct: number | null;
  wind_speed_kph: number | null;
  rainfall: boolean;
};

export type WeatherPlot = {
  /** Every sample that could be placed in time, earliest first. */
  points: WeatherPoint[];
  sampleCount: number;
  /** Samples left out because their time could not be read. */
  untimedCount: number;
  /** Plotted samples taken while it was raining. */
  rainCount: number;
};

export function weatherPlot(samples: ReadonlyArray<WeatherSample>): WeatherPlot {
  const points: WeatherPoint[] = [];
  for (const sample of samples) {
    const time = parsePandasDuration(sample.timestamp);
    if (time !== null) {
      points.push({
        time_ms: time,
        air_temp_c: measured(sample.air_temp_c),
        track_temp_c: measured(sample.track_temp_c),
        humidity_pct: measured(sample.humidity_pct),
        wind_speed_kph: measured(sample.wind_speed_kph),
        rainfall: sample.rainfall === true
      });
    }
  }
  points.sort((left, right) => left.time_ms - right.time_ms);
  return {
    points,
    sampleCount: samples.length,
    untimedCount: samples.length - points.length,
    rainCount: points.filter((point) => point.rainfall).length
  };
}

/** What is in the chart and what is not, in a sentence or two. */
export function describeWeatherPlot(plot: WeatherPlot): string {
  if (plot.sampleCount === 0) {
    return "No weather samples in this session.";
  }
  const sentences = [
    plot.untimedCount === 0
      ? `${count(plot.sampleCount, "sample")}.`
      : `${plot.points.length} of ${count(plot.sampleCount, "sample")} plotted; the rest carry no readable time.`
  ];
  if (plot.points.length > 0) {
    sentences.push(
      plot.rainCount === 0
        ? "No rain was recorded."
        : `Rain was recorded in ${plot.rainCount} of ${count(plot.points.length, "plotted sample")}.`
    );
  }
  return sentences.join(" ");
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

function measured(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function count(value: number, noun: string): string {
  return `${value} ${noun}${value === 1 ? "" : "s"}`;
}
