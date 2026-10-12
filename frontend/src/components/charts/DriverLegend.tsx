"use client";

import clsx from "clsx";
import { useState } from "react";

import { DriverMark, type DriverMarkKind } from "@/components/charts/DriverMark";
import {
  hideAllDrivers,
  NO_HIDDEN_DRIVERS,
  selectionSummary,
  toggleDriver,
  visibleDrivers,
  type HiddenDrivers
} from "@/lib/driver-selection";
import { driverStyle, type DriverStyles } from "@/lib/driver-style";

export type DriverSelection = {
  hidden: HiddenDrivers;
  toggle: (driver: string) => void;
  showAll: () => void;
  hideAll: () => void;
};

/** Selection state for one chart: every driver shown until the reader hides some. */
export function useDriverSelection(drivers: ReadonlyArray<string>): DriverSelection {
  const [hidden, setHidden] = useState<HiddenDrivers>(NO_HIDDEN_DRIVERS);
  return {
    hidden,
    toggle: (driver) => setHidden((current) => toggleDriver(current, driver)),
    showAll: () => setHidden(NO_HIDDEN_DRIVERS),
    hideAll: () => setHidden(hideAllDrivers(drivers))
  };
}

type DriverLegendProps = {
  drivers: ReadonlyArray<string>;
  styles: DriverStyles;
  selection: DriverSelection;
  mark: DriverMarkKind;
};

/**
 * The legend of a chart that draws one series per driver. Each entry is a
 * toggle, and the line above the entries says how many drivers are on screen.
 */
export function DriverLegend({ drivers, styles, selection, mark }: DriverLegendProps) {
  const shownCount = visibleDrivers(drivers, selection.hidden).length;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <span className="font-semibold text-slate-300" aria-live="polite">
          {selectionSummary(drivers, selection.hidden)}
        </span>
        <LegendAction label="Show all" onClick={selection.showAll} disabled={shownCount === drivers.length} />
        <LegendAction label="Hide all" onClick={selection.hideAll} disabled={shownCount === 0} />
        <span>
          {mark === "line"
            ? "Team-mates share a colour: one line is solid, the other dashed."
            : "Team-mates share a colour: one marker is filled, the other hollow."}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Drivers shown in the chart">
        {drivers.map((driver) => {
          const shown = !selection.hidden.has(driver);
          return (
            <button
              key={driver}
              type="button"
              aria-pressed={shown}
              title={shown ? `Hide ${driver}` : `Show ${driver}`}
              onClick={() => selection.toggle(driver)}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded border px-2 py-1 font-mono text-xs font-semibold transition",
                shown
                  ? "border-line bg-white/[0.05] text-slate-100 hover:border-slate-500"
                  : "border-line/50 text-slate-600 hover:text-slate-400"
              )}
            >
              <DriverMark style={driverStyle(styles, driver)} mark={mark} muted={!shown} />
              {driver}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function LegendAction({ label, onClick, disabled }: { label: string; onClick: () => void; disabled: boolean }) {
  return (
    <button
      type="button"
      className="rounded border border-line px-2 py-0.5 text-xs text-slate-300 transition hover:border-slate-500 disabled:opacity-40"
      onClick={onClick}
      disabled={disabled}
    >
      {label}
    </button>
  );
}
