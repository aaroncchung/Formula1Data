import type { Lap, TyreDegradationRow } from "./published/types.ts";

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
  shown: ReadonlyArray<TyreDegradationRow>;
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

/** How many of these drivers' stints have a reported rate, as opposed to a row that says there is none. */
export function reportedFitCount(rows: ReadonlyArray<TyreDegradationRow>, drivers: ReadonlyArray<string>): number {
  const wanted = new Set(drivers);
  return rows.filter((row) => wanted.has(row.driver_code) && tyreFit(row).status === "reported").length;
}

export type TyreFit =
  | {
      status: "reported";
      /** The fuel-adjusted rate. Positive is a tyre getting slower. */
      rate_ms_per_lap: number;
      /** One standard error of the fitted slope; null when it was not published. */
      standard_error_ms_per_lap: number | null;
    }
  /**
   * No rate. `poor_fit`: the laps scatter too much to fix the slope.
   * `too_few_laps`: too few clean laps to fit. `not_reported`: the fit is
   * marked as good and the row holds no rate. `reason` is the publisher's
   * own sentence where it gave one.
   */
  | { status: "poor_fit" | "too_few_laps" | "not_reported"; reason: string };

/**
 * How many laps a stint's fit is of, or null for a stint no fit was made of.
 *
 * The row counts the laps a fit could use, and apart from that how many of
 * them it left out as outliers. The table printed the first under "Laps
 * fitted", beside the second: 23 for Antonelli's second stint of the 2026
 * Austrian GP, whose slope is of 22.
 */
export function lapsFitted(row: Pick<TyreDegradationRow, "fit_status" | "sample_count" | "excluded_outlier_count">): number | null {
  return row.fit_status === "too_few_laps" ? null : row.sample_count - row.excluded_outlier_count;
}

/**
 * Whether a degradation row holds a rate, and if not, why not.
 *
 * A fit the analysis did not report has to stay unreported on the page: its
 * row still carries a stint and a lap count, and a table that prints "-- ms/lap"
 * or a zero for it reads as a measured rate. The status decides, so a row
 * marked as a poor fit shows no rate even if it carries a number.
 */
export function tyreFit(row: TyreDegradationRow): TyreFit {
  const reason = row.caveats.find((caveat) => caveat.trim() !== "");
  switch (row.fit_status) {
    case "poor_fit":
    case "too_few_laps":
      return { status: row.fit_status, reason: reason ?? UNREPORTED_REASONS[row.fit_status] };
    case "ok":
      // The format gives a rate with every good fit. One without is shown
      // as having none, which is what it has.
      return row.degradation_ms_per_lap === null
        ? { status: "not_reported", reason: UNREPORTED_REASONS.not_reported }
        : {
            status: "reported",
            rate_ms_per_lap: row.degradation_ms_per_lap,
            standard_error_ms_per_lap: row.slope_standard_error_ms_per_lap
          };
  }
}

const UNREPORTED_REASONS = {
  poor_fit: "No rate reported: the lap times scatter too much to fix the slope.",
  too_few_laps: "No rate reported: too few clean laps in the stint.",
  not_reported: "No rate was published for this stint."
} as const;

/** A fit in a few words, for a card or a table cell. */
export function tyreFitLabel(fit: TyreFit): string {
  switch (fit.status) {
    case "reported":
      return formatRate(fit.rate_ms_per_lap);
    case "poor_fit":
      return "No rate: laps too scattered";
    case "too_few_laps":
      return "No rate: too few laps";
    case "not_reported":
      return "No rate";
  }
}

/** A rate with its sign, `+45.2 ms/lap`: the sign is the finding. */
export function formatRate(value: number | null | undefined): string {
  if (!isMeasured(value)) {
    return "--";
  }
  const rounded = Number(value.toFixed(1));
  // Rounded before the sign is chosen, so -0.04 reads "0.0" and not "-0.0".
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)} ms/lap`;
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
