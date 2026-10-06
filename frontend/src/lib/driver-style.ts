/**
 * How a driver is drawn in every chart that colours by team.
 *
 * Team-mates keep the team colour. What tells them apart is the variant: the
 * first driver in a colour is drawn solid and filled, the second dashed and
 * hollow. Drivers are grouped by the colour itself, not by team, because the
 * question a chart has to answer is "which of the marks in this colour is
 * which". Grouping by colour also separates two teams that share a colour and
 * a field that has no colours at all.
 *
 * Within a colour the order is by driver code, so a driver looks the same in
 * every chart and every session whatever order the data lists the field in.
 */

export const FALLBACK_DRIVER_COLOR = "#94a3b8";

/**
 * Line patterns by variant; `undefined` is a solid line. Every published
 * session has at most two drivers per colour. The later patterns are for data
 * that shares a colour more widely, and they repeat after the fourth.
 */
const DASH_PATTERNS: ReadonlyArray<string | undefined> = [undefined, "6 4", "2 4", "10 4 2 4"];

export type DriverStyle = {
  color: string;
  /** Position among the drivers that share this colour: 0 first, 1 second. */
  variant: number;
  /** SVG `stroke-dasharray` for a line; `undefined` draws it solid. */
  dash: string | undefined;
  /** Whether a marker is drawn as an outline instead of filled. */
  hollow: boolean;
};

export type DriverStyles = ReadonlyMap<string, DriverStyle>;

type StyledDriver = { code: string; color?: string | null };

type TeamDriver = { code: string; team: { color?: string | null } };

/** Styles for a session's drivers, each in their team's colour. */
export function teamDriverStyles(drivers: ReadonlyArray<TeamDriver>): DriverStyles {
  return assignDriverStyles(drivers.map((driver) => ({ code: driver.code, color: driver.team.color })));
}

/**
 * Each driver's team colour alone, for a mark that sits beside the driver's
 * code and so does not have to tell team-mates apart.
 */
export function teamColorByDriver(drivers: ReadonlyArray<TeamDriver>): Record<string, string | null | undefined> {
  return Object.fromEntries(drivers.map((driver) => [driver.code, driver.team.color]));
}

export function assignDriverStyles(drivers: ReadonlyArray<StyledDriver>): DriverStyles {
  const codesByColor = new Map<string, string[]>();
  const seen = new Set<string>();
  for (const driver of drivers) {
    if (seen.has(driver.code)) {
      continue;
    }
    seen.add(driver.code);
    const color = normalizeColor(driver.color);
    const codes = codesByColor.get(color);
    if (codes) {
      codes.push(driver.code);
    } else {
      codesByColor.set(color, [driver.code]);
    }
  }

  const styles = new Map<string, DriverStyle>();
  for (const [color, codes] of codesByColor) {
    [...codes].sort(compareCodes).forEach((code, variant) => {
      styles.set(code, {
        color,
        variant,
        dash: DASH_PATTERNS[variant % DASH_PATTERNS.length],
        hollow: variant % 2 === 1
      });
    });
  }
  return styles;
}

/** The style for one driver, or a plain grey one for a driver the styles do not cover. */
export function driverStyle(styles: DriverStyles, code: string): DriverStyle {
  return styles.get(code) ?? { color: FALLBACK_DRIVER_COLOR, variant: 0, dash: undefined, hollow: false };
}

function normalizeColor(color: string | null | undefined): string {
  const trimmed = color?.trim().toLowerCase();
  return trimmed ? trimmed : FALLBACK_DRIVER_COLOR;
}

function compareCodes(left: string, right: string): number {
  if (left === right) {
    return 0;
  }
  return left < right ? -1 : 1;
}
