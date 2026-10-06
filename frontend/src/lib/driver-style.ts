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

export function assignDriverStyles(drivers: ReadonlyArray<StyledDriver>): DriverStyles {
  return assignInTiers([drivers]);
}

/**
 * Styles for a session's drivers, each in their team's colour.
 *
 * Every chart of a session starts from the same driver list, so a driver is
 * drawn the same way in all of them. `others` is for the drivers a chart has
 * data for that the list does not name: they are styled too, after the listed
 * drivers, and never change how a listed driver looks.
 */
export function teamDriverStyles(
  drivers: ReadonlyArray<TeamDriver>,
  others: ReadonlyArray<StyledDriver> = []
): DriverStyles {
  return assignInTiers([drivers.map((driver) => ({ code: driver.code, color: driver.team.color })), others]);
}

/**
 * Each driver's team colour alone, for a mark that sits beside the driver's
 * code and so does not have to tell team-mates apart.
 */
export function teamColorByDriver(drivers: ReadonlyArray<TeamDriver>): Record<string, string | null | undefined> {
  return Object.fromEntries(drivers.map((driver) => [driver.code, driver.team.color]));
}

/** The style for one driver, or a plain grey one for a driver the styles do not cover. */
export function driverStyle(styles: DriverStyles, code: string): DriverStyle {
  return styles.get(code) ?? { color: FALLBACK_DRIVER_COLOR, variant: 0, dash: undefined, hollow: false };
}

/**
 * Within a colour, drivers of an earlier tier come first and each tier is in
 * code order. A driver named in more than one place keeps its first entry.
 */
function assignInTiers(tiers: ReadonlyArray<ReadonlyArray<StyledDriver>>): DriverStyles {
  const entriesByColor = new Map<string, Array<{ code: string; tier: number }>>();
  const seen = new Set<string>();
  tiers.forEach((drivers, tier) => {
    for (const driver of drivers) {
      if (seen.has(driver.code)) {
        continue;
      }
      seen.add(driver.code);
      const color = normalizeColor(driver.color);
      const entries = entriesByColor.get(color) ?? [];
      entriesByColor.set(color, entries);
      entries.push({ code: driver.code, tier });
    }
  });

  const styles = new Map<string, DriverStyle>();
  for (const [color, entries] of entriesByColor) {
    entries
      .sort((left, right) => left.tier - right.tier || compareCodes(left.code, right.code))
      .forEach((entry, variant) => {
        styles.set(entry.code, {
          color,
          variant,
          dash: DASH_PATTERNS[variant % DASH_PATTERNS.length],
          hollow: variant % 2 === 1
        });
      });
  }
  return styles;
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
