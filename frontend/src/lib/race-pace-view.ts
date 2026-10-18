import type { RacePaceRow } from "./published/types.ts";

/**
 * The rows the race-pace chart ranks, and the drivers it leaves out.
 *
 * A row with no gap ran too few clean laps to be ranked (the analysis's
 * caveats say why). Its median is over the opening laps, on a full tank, so a
 * bar for it beside the others reads as a driver that was slow.
 */
export function racePaceChartRows(rows: ReadonlyArray<RacePaceRow>): {
  readonly ranked: ReadonlyArray<RacePaceRow>;
  readonly unranked: ReadonlyArray<string>;
} {
  const ranked = rows.filter((row) => row.gap_to_best_ms !== null);
  const unranked = rows.filter((row) => row.gap_to_best_ms === null).map((row) => row.driver_code);
  return { ranked, unranked };
}
