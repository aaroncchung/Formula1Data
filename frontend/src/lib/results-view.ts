/**
 * What a classification row says, in the words a table prints.
 *
 * The format has a field for each thing a time column can mean, where format
 * 1 had one field for all of them: the winner's race time (`time_ms`), the
 * gap of a driver who finished on the winner's lap (`gap_ms`), and for a
 * driver who took the flag a lap or more behind, how many laps
 * (`laps_down`). How long after the winner such a driver crossed the line
 * (`behind_at_flag_ms`) is not a gap to anyone, since they had fewer laps to
 * run: in the 2026 Austrian GP it puts Lawson, a lap down in ninth, 15.3 s
 * behind the winner and Leclerc, eighth on the lead lap, 45.7 s behind. It is
 * shown beside the laps down and never in place of them.
 */

import { formatDuration, formatElapsed } from "./pandas-time.ts";
import type { Result } from "./published/types.ts";

/** A cell: what it prints, and anything more that is true of it, for a tooltip. */
export type ResultCell = { readonly text: string; readonly note: string | null };

/** The time column: a race time, a gap, laps down, or nothing. */
export function resultTime(result: Result): ResultCell {
  if (result.time_ms !== null) {
    return { text: formatDuration(result.time_ms), note: "The winner's race time." };
  }
  if (result.gap_ms !== null) {
    return { text: `+${formatElapsed(result.gap_ms)}`, note: null };
  }
  if (result.laps_down !== null) {
    const laps = `${result.laps_down} ${result.laps_down === 1 ? "lap" : "laps"}`;
    return {
      text: `+${laps}`,
      note:
        result.behind_at_flag_ms === null
          ? null
          : `Took the flag ${formatElapsed(result.behind_at_flag_ms)} after the winner, ${laps} down. That is not a gap to the winner.`
    };
  }
  return { text: "--", note: null };
}

// The letters a classification gives in place of a number.
const CLASSIFICATION_LETTERS: Readonly<Record<string, string>> = {
  R: "Retired",
  D: "Disqualified",
  E: "Excluded",
  W: "Withdrawn",
  F: "Failed to qualify",
  N: "Not classified"
};

const WHOLE_NUMBER = /^[0-9]+$/;

/**
 * The place a driver was classified in, or null when the classification
 * gives them a letter or leaves them out. A provisional order has no
 * classification to print, and its place is the position in the timing.
 */
export function classifiedPlace(result: Result): number | null {
  const printed = result.classified_position?.trim() ?? "";
  if (printed === "") {
    return result.position;
  }
  return WHOLE_NUMBER.test(printed) ? Number(printed) : null;
}

/**
 * The position column, as the classification prints it: a number, or its
 * letter for a driver it does not place, such as R for a retirement.
 */
export function resultPosition(result: Result): ResultCell {
  const place = classifiedPlace(result);
  if (place !== null) {
    return { text: String(place), note: null };
  }
  const letter = result.classified_position?.trim() ?? "";
  if (letter === "") {
    return { text: "--", note: "Took part and is not in the classification." };
  }
  return { text: letter, note: CLASSIFICATION_LETTERS[letter.toUpperCase()] ?? null };
}

/** The grid column. The classification writes a start from the pit lane as place 0. */
export function gridLabel(grid: number | null): string {
  if (grid === null) {
    return "--";
  }
  return grid === 0 ? "Pit lane" : String(grid);
}

/** Points, or a dash where none were published: an order with no classification has no points, not zero. */
export function pointsLabel(points: number | null): string {
  return points === null ? "--" : String(points);
}

/**
 * Whether these rows are the order on track from the timing alone, because
 * no classification has been published for the session. They then carry no
 * status, points or grid, and the table has to say why.
 */
export function isProvisional(results: ReadonlyArray<Result>): boolean {
  return results.some((row) => row.provisional);
}
