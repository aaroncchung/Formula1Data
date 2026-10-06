/**
 * How a team-mate comparison row is read for display
 * (`calculate_teammate_comparison` in
 * backend/app/analysis/teammate_comparison.py).
 *
 * The row lists the quicker driver first and its gap is never negative, so
 * the gap is shown as "who, by how much" and not as a signed number. A row can
 * also have no gap at all, when the two cars shared too few clean laps; that
 * is said in words, never drawn as a zero or a dash that reads like a tie.
 */

import type { TeammateComparisonRow } from "@/types/domain";

export type TeammateGap =
  | { status: "reported"; quicker: string; slower: string; gap_ms: number }
  /** Both drivers named, in the order the row lists them. */
  | { status: "level"; drivers: [string, string] }
  /** `reason` is the row's own caveat when it has one. */
  | { status: "none"; reason: string };

export function teammateGap(row: TeammateComparisonRow): TeammateGap {
  const [first, second] = row.drivers;
  const gap = row.gap_ms;
  if (!first || !second || typeof gap !== "number" || !Number.isFinite(gap)) {
    return { status: "none", reason: row.caveat?.trim() || "No gap was published for this team." };
  }
  if (gap === 0) {
    return { status: "level", drivers: [first.driver_code, second.driver_code] };
  }
  // The publisher puts the quicker driver first. A negative gap would mean it
  // did not, and then the second driver is the quicker one.
  return gap > 0
    ? { status: "reported", quicker: first.driver_code, slower: second.driver_code, gap_ms: gap }
    : { status: "reported", quicker: second.driver_code, slower: first.driver_code, gap_ms: -gap };
}

export function teammateGapText(gap: TeammateGap): string {
  switch (gap.status) {
    case "reported":
      return `${gap.quicker} quicker by ${seconds(gap.gap_ms)}`;
    case "level":
      return "Level";
    case "none":
      return "No gap";
  }
}

/**
 * What the gap rests on: how many laps were matched, how many of those were
 * trimmed, and how much the lap-by-lap difference moves around. Null for a
 * row from before these were published, which says nothing about its laps.
 */
export function teammateBasis(row: TeammateComparisonRow): string | null {
  const matched = row.matched_lap_count;
  if (typeof matched !== "number") {
    return null;
  }
  const parts = [`${matched} matched ${matched === 1 ? "lap" : "laps"}`];
  if (typeof row.trimmed_lap_count === "number" && row.trimmed_lap_count > 0) {
    parts.push(`${row.trimmed_lap_count} trimmed`);
  }
  if (typeof row.gap_spread_ms === "number" && Number.isFinite(row.gap_spread_ms)) {
    parts.push(`lap-to-lap spread ${seconds(row.gap_spread_ms)}`);
  }
  return parts.join(" · ");
}

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(3)}s`;
}
