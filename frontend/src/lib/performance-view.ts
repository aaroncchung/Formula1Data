/**
 * How the telemetry analyses are read for display: the minisector count of a
 * track-dominance result, and which analyses a session has nothing to show
 * for and why.
 */

import type {
  CarPerformanceResult,
  CornerAnalysisResult,
  PacePredictionResult,
  TrackDominanceResult
} from "@/types/domain";

export type MinisectorTally = {
  driver: string;
  /** Minisectors in which this driver was the quickest. */
  won: number;
  /**
   * Minisectors in which this driver has a time at all. A driver is left out
   * of a minisector where their telemetry has a hole at one of its
   * boundaries, so this can be short of the total, and "won 3" means less
   * out of 19 than out of 25.
   */
  timed: number;
};

/** Each driver who won a minisector, most wins first, then by code. */
export function minisectorTally(result: TrackDominanceResult): MinisectorTally[] {
  const tallies = new Map<string, MinisectorTally>();
  for (const sector of result.minisectors) {
    const winner = sector.winner_driver_code;
    if (!winner) {
      continue;
    }
    const tally = tallies.get(winner) ?? { driver: winner, won: 0, timed: 0 };
    tallies.set(winner, tally);
    tally.won += 1;
  }
  for (const tally of tallies.values()) {
    tally.timed = result.minisectors.filter((sector) => isMeasured(sector.driver_times_ms?.[tally.driver])).length;
  }
  return [...tallies.values()].sort(
    (left, right) => right.won - left.won || compareCodes(left.driver, right.driver)
  );
}

export type AnalysisNotice = { title: string; reason: string };

type TelemetryAnalyses = {
  trackDominance: TrackDominanceResult | null;
  carPerformance: CarPerformanceResult | null;
  cornerAnalysis: CornerAnalysisResult | null;
  pacePrediction: PacePredictionResult | null;
};

const NOT_PUBLISHED = "Not part of this session's published data.";

/**
 * The analyses with nothing to show, each with its reason, so that a missing
 * panel is accounted for on the page. `null` is an artifact the generation
 * does not hold. An artifact that is there and empty explains itself in the
 * last of its caveats, which is where the analysis puts the reason.
 */
export function unavailableAnalyses(analyses: TelemetryAnalyses): AnalysisNotice[] {
  const notices: AnalysisNotice[] = [];
  const { trackDominance, carPerformance, cornerAnalysis, pacePrediction } = analyses;

  if (!trackDominance) {
    notices.push({ title: "Track dominance", reason: NOT_PUBLISHED });
  } else if (trackDominance.minisectors.length === 0) {
    notices.push({ title: "Track dominance", reason: lastCaveat(trackDominance.caveats, "No usable telemetry laps were available.") });
  }

  if (!carPerformance) {
    notices.push({ title: "Car performance profile", reason: NOT_PUBLISHED });
  } else if (carPerformance.drivers.length === 0) {
    // This analysis has no caveat for the empty case; its caveats describe the method.
    notices.push({ title: "Car performance profile", reason: "No lap with usable telemetry." });
  }

  if (!cornerAnalysis) {
    notices.push({ title: "Corner analysis", reason: NOT_PUBLISHED });
  } else if (cornerAnalysis.corners.length === 0) {
    notices.push({ title: "Corner analysis", reason: lastCaveat(cornerAnalysis.caveats, "No braking events were detected.") });
  }

  if (!pacePrediction) {
    notices.push({ title: "Race-pace prediction", reason: NOT_PUBLISHED });
  } else if (!pacePrediction.available || pacePrediction.drivers.length === 0) {
    notices.push({ title: "Race-pace prediction", reason: lastCaveat(pacePrediction.caveats, "No long runs to estimate from.") });
  }

  return notices;
}

function lastCaveat(caveats: ReadonlyArray<string> | undefined, fallback: string): string {
  return caveats?.at(-1)?.trim() || fallback;
}

function isMeasured(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function compareCodes(left: string, right: string): number {
  if (left === right) {
    return 0;
  }
  return left < right ? -1 : 1;
}
