/**
 * How the telemetry analyses are read for display: the minisector count of a
 * track-dominance result, how a corner of the corner analysis is named, and
 * which analyses a session has nothing to show for and why.
 */

import type { CarPerformance, CornerAnalysis, PacePrediction, TrackDominance } from "./published/types.ts";

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
export function minisectorTally(result: TrackDominance): MinisectorTally[] {
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
    // A driver with no time in a minisector is not in its times at all.
    tally.timed = result.minisectors.filter((sector) => Object.hasOwn(sector.driver_times_ms, tally.driver)).length;
  }
  return [...tallies.values()].sort(
    (left, right) => right.won - left.won || compareCodes(left.driver, right.driver)
  );
}

type AnalysedCorner = CornerAnalysis["corners"][number];

/**
 * What a corner of the corner analysis is called.
 *
 * With official corners the number is the circuit's own, and a letter tells
 * apart the corners that share one: "Turn 1A". When the circuit's corner
 * positions could not be used, the analysis finds the places cars braked and
 * numbers them in the order they come, which is not the circuit's numbering,
 * so it is not written as a turn.
 */
export function cornerName(corner: Pick<AnalysedCorner, "corner_number" | "letter">, source: CornerAnalysis["corner_source"]): string {
  return source === "official"
    ? `Turn ${corner.corner_number}${corner.letter ?? ""}`
    : `Braking zone ${corner.corner_number}`;
}

/**
 * What to say where a driver's row for a corner has no brake point.
 *
 * Two things leave it empty. The driver took the corner without braking,
 * which the analysis knows when the brake was read all the way in. Or F1's
 * car feed had no brake reading on the approach, and then nothing is known:
 * Gasly into turn 9 on lap 56 of the 2026 Australian GP, from 311 km/h to
 * 218 with no reading, was shown as "No braking".
 *
 * A generation built before `braking` says it with `brake_known`, and one
 * built before that says nothing. Both are still read while the sessions
 * are rebuilt, so the older word is kept: without it that same row of
 * Gasly's, from a generation that knew, was "No braking" again.
 */
export function noBrakePoint(row: { braking?: string; brake_known?: boolean }): string {
  switch (row.braking) {
    case "unread":
      return "No brake reading";
    case "began_unread":
      // Seen braking, from the sample the reading came back on: they braked, from somewhere before it.
      return "Braked, point not known";
    case "none":
    case "seen":
      return "No braking";
    default:
      return row.brake_known === false ? "No brake reading" : "No braking";
  }
}

/**
 * Where a corner is on the lap a row's figures are from, in metres, or null
 * when the generation does not say.
 *
 * The row's brake point is along the driver's own lap, and laps disagree
 * about distance: on Stroll's lap 30 of the 2026 Austrian GP turn 6 is at
 * 2,554 m, and the table put "At 2,518 m" beside his figures, which is where
 * the lap the corners were placed on has it. A generation from before each
 * row said where its own lap has the corner has no place to show, and the
 * other lap's is not shown in its stead.
 */
export function cornerPlace(row: { corner_distance_m?: number | null }): number | null {
  return row.corner_distance_m ?? null;
}

/** What the corners of an analysis are, in a sentence, for the panel that lists them. */
export function cornerSourceNote(source: CornerAnalysis["corner_source"]): string {
  return source === "official"
    ? "Braking, apex and exit at each of the circuit's own corners, on each driver's representative lap."
    : "The circuit's corner positions could not be used for this session, so these are the places the telemetry shows cars braking, numbered in the order they come and not as the circuit numbers its turns.";
}

export type AnalysisNotice = { title: string; reason: string };

type TelemetryAnalyses = {
  trackDominance: TrackDominance | null;
  carPerformance: CarPerformance | null;
  cornerAnalysis: CornerAnalysis | null;
  pacePrediction: PacePrediction | null;
  /** The session's code, such as R or FP2. */
  sessionType: string;
};

const NOT_PUBLISHED = "Not part of this session's published data.";
const PRACTICE = /^FP[0-9]$/;

/**
 * The analyses with nothing to show, each with its reason, so that a missing
 * panel is accounted for on the page. `null` is an artifact the generation
 * does not hold. An artifact that is there and empty explains itself in the
 * last of its caveats, which is where the analysis puts the reason.
 */
export function unavailableAnalyses(analyses: TelemetryAnalyses): AnalysisNotice[] {
  const notices: AnalysisNotice[] = [];
  const { trackDominance, carPerformance, cornerAnalysis, pacePrediction, sessionType } = analyses;

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
    // The prediction is made from practice long runs, so only a practice
    // session is published with one. For any other session its absence is
    // how the format works and not something that went missing.
    notices.push({
      title: "Race-pace prediction",
      reason: PRACTICE.test(sessionType.toUpperCase()) ? NOT_PUBLISHED : "Made from practice long runs, so only a practice session has one."
    });
  } else if (!pacePrediction.available || pacePrediction.drivers.length === 0) {
    notices.push({ title: "Race-pace prediction", reason: lastCaveat(pacePrediction.caveats, "No long runs to estimate from.") });
  }

  return notices;
}

function lastCaveat(caveats: ReadonlyArray<string>, fallback: string): string {
  return caveats.at(-1)?.trim() || fallback;
}

function compareCodes(left: string, right: string): number {
  if (left === right) {
    return 0;
  }
  return left < right ? -1 : 1;
}
