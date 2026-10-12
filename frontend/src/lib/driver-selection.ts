/**
 * Which drivers a chart is showing.
 *
 * A chart starts with every driver its data has. Focus works by subtraction:
 * the set holds the drivers a reader has hidden, so nothing is left out by
 * default and a driver the data gains later is shown without anyone opting in.
 */

export type HiddenDrivers = ReadonlySet<string>;

export const NO_HIDDEN_DRIVERS: HiddenDrivers = new Set<string>();

/** Hide a shown driver, or show a hidden one. */
export function toggleDriver(hidden: HiddenDrivers, driver: string): HiddenDrivers {
  const next = new Set(hidden);
  if (!next.delete(driver)) {
    next.add(driver);
  }
  return next;
}

export function hideAllDrivers(drivers: ReadonlyArray<string>): HiddenDrivers {
  return new Set(drivers);
}

/** The drivers still shown, in the order the chart lists them. */
export function visibleDrivers(drivers: ReadonlyArray<string>, hidden: HiddenDrivers): string[] {
  return drivers.filter((driver) => !hidden.has(driver));
}

/** States how much of the field is on screen, so a hidden driver is never silent. */
export function selectionSummary(drivers: ReadonlyArray<string>, hidden: HiddenDrivers): string {
  const total = drivers.length;
  if (total === 0) {
    return "No drivers in this data";
  }
  const shown = visibleDrivers(drivers, hidden).length;
  const noun = total === 1 ? "driver" : "drivers";
  if (shown === total) {
    return `All ${total} ${noun} shown`;
  }
  return `${shown} of ${total} ${noun} shown`;
}
