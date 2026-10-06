import type { Lap, TyreDegradationRow } from "@/types/domain";

/**
 * The data behind the tyre degradation chart: lap time against tyre age for
 * every driver that has a lap. Laps that cannot be plotted are counted, not
 * dropped quietly, so the chart can say what it left out.
 */

export type TyreAgePoint = {
  driver_code: string;
  lap_number: number;
  tyre_age: number;
  lap_time_ms: number;
  compound: string | null;
};

export type TyreAgeDriver = { driver: string; points: TyreAgePoint[] };

export type TyreAgePlot = {
  /** Every driver with a lap, by driver code, including any with nothing to plot. */
  drivers: TyreAgeDriver[];
  lapCount: number;
  plottedCount: number;
  /** Laps left out because the car entered or left the pits on them. */
  pitLapCount: number;
  /** Laps left out because they carry no lap time or no tyre age. */
  incompleteLapCount: number;
};

export function tyreAgePlot(laps: ReadonlyArray<Lap>): TyreAgePlot {
  const pointsByDriver = new Map<string, TyreAgePoint[]>();
  let pitLapCount = 0;
  let incompleteLapCount = 0;

  for (const lap of laps) {
    const points = pointsByDriver.get(lap.driver_code) ?? [];
    pointsByDriver.set(lap.driver_code, points);

    const lapTime = lap.lap_time_ms;
    const tyreAge = lap.tyre_age;
    if (!isMeasured(lapTime) || lapTime <= 0 || !isMeasured(tyreAge)) {
      incompleteLapCount += 1;
    } else if (lap.is_pit_in_lap || lap.is_pit_out_lap) {
      pitLapCount += 1;
    } else {
      points.push({
        driver_code: lap.driver_code,
        lap_number: lap.lap_number,
        tyre_age: tyreAge,
        lap_time_ms: lapTime,
        compound: lap.compound ?? null
      });
    }
  }

  const drivers = Array.from(pointsByDriver, ([driver, points]) => ({ driver, points })).sort((left, right) =>
    compareCodes(left.driver, right.driver)
  );
  return {
    drivers,
    lapCount: laps.length,
    plottedCount: laps.length - pitLapCount - incompleteLapCount,
    pitLapCount,
    incompleteLapCount
  };
}

/** One sentence or two on how much of the data is in the chart, and what is not. */
export function describeTyreAgePlot(plot: TyreAgePlot): string {
  if (plot.lapCount === 0) {
    return "No laps in this session.";
  }
  const sentences: string[] = [];
  if (plot.plottedCount === plot.lapCount) {
    sentences.push(`All ${count(plot.lapCount, "lap")} plotted.`);
  } else {
    const reasons = [
      plot.pitLapCount ? `${count(plot.pitLapCount, "pit-in or pit-out lap")}` : null,
      plot.incompleteLapCount ? `${count(plot.incompleteLapCount, "lap")} without a lap time or tyre age` : null
    ].filter((reason): reason is string => reason !== null);
    sentences.push(`${plot.plottedCount.toLocaleString("en-US")} of ${count(plot.lapCount, "lap")} plotted.`);
    sentences.push(`Left out: ${reasons.join(" and ")}.`);
  }
  const empty = plot.drivers.filter((entry) => entry.points.length === 0).map((entry) => entry.driver);
  if (empty.length) {
    sentences.push(`Nothing to plot for ${empty.join(", ")}.`);
  }
  return sentences.join(" ");
}

/** Narrows a Recharts tooltip payload, which is untyped, back to a plotted lap. */
export function isTyreAgePoint(value: unknown): value is TyreAgePoint {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  return (
    "driver_code" in value &&
    typeof value.driver_code === "string" &&
    "lap_number" in value &&
    typeof value.lap_number === "number" &&
    "tyre_age" in value &&
    typeof value.tyre_age === "number" &&
    "lap_time_ms" in value &&
    typeof value.lap_time_ms === "number"
  );
}

export type TyreFitSelection = {
  shown: TyreDegradationRow[];
  /** Fits that belong to the drivers on screen, shown or not. */
  total: number;
};

/**
 * The stint fits of the drivers on screen, cut to `limit`. `total` keeps the
 * uncut count so the caller can say how many it is not showing.
 */
export function tyreFitsFor(
  rows: ReadonlyArray<TyreDegradationRow>,
  drivers: ReadonlyArray<string>,
  limit: number
): TyreFitSelection {
  const wanted = new Set(drivers);
  const matching = rows.filter((row) => wanted.has(row.driver_code));
  return { shown: matching.slice(0, Math.max(limit, 0)), total: matching.length };
}

function isMeasured(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function count(value: number, noun: string): string {
  return `${value.toLocaleString("en-US")} ${noun}${value === 1 ? "" : "s"}`;
}

function compareCodes(left: string, right: string): number {
  if (left === right) {
    return 0;
  }
  return left < right ? -1 : 1;
}
