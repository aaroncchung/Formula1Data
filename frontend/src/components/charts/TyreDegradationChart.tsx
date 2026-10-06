"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
  type TooltipContentProps
} from "recharts";

import { DriverLegend, useDriverSelection } from "@/components/charts/DriverLegend";
import { CHART_TOOLTIP_STYLE } from "@/lib/chart-utils";
import { visibleDrivers } from "@/lib/driver-selection";
import { driverStyle, teamDriverStyles } from "@/lib/driver-style";
import { formatMs } from "@/lib/format";
import { describeTyreAgePlot, isTyreAgePoint, tyreAgePlot, tyreFitsFor } from "@/lib/tyre-chart";
import type { Driver, Lap, TyreDegradationResult } from "@/types/domain";

/** Stint fits shown before the reader asks for the rest: three rows of cards. */
const FIT_PREVIEW_COUNT = 9;

export function TyreDegradationChart({
  laps,
  degradation,
  drivers
}: {
  laps: Lap[];
  degradation: TyreDegradationResult;
  drivers: Driver[];
}) {
  const plot = useMemo(() => tyreAgePlot(laps), [laps]);
  const codes = useMemo(() => plot.drivers.map((entry) => entry.driver), [plot]);
  const styles = useMemo(
    () => teamDriverStyles(drivers, codes.map((code) => ({ code }))),
    [drivers, codes]
  );
  const selection = useDriverSelection(codes);
  const [showAllFits, setShowAllFits] = useState(false);

  const shown = new Set(visibleDrivers(codes, selection.hidden));
  const fits = tyreFitsFor(degradation.rows, [...shown], showAllFits ? degradation.rows.length : FIT_PREVIEW_COUNT);

  return (
    <div className="space-y-4">
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="#293246" strokeDasharray="3 3" />
            <XAxis dataKey="tyre_age" name="Tyre age" type="number" allowDecimals={false} stroke="#94a3b8" />
            <YAxis
              dataKey="lap_time_ms"
              name="Lap time"
              type="number"
              stroke="#94a3b8"
              tickFormatter={(value) => formatMs(Number(value))}
            />
            <ZAxis range={[30, 30]} />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} content={TyreAgeTooltip} />
            {plot.drivers
              .filter((entry) => shown.has(entry.driver))
              .map((entry) => {
                const style = driverStyle(styles, entry.driver);
                return (
                  <Scatter
                    key={entry.driver}
                    name={entry.driver}
                    data={entry.points}
                    fill={style.color}
                    fillOpacity={style.hollow ? 0 : 1}
                    stroke={style.color}
                    strokeWidth={1.5}
                    isAnimationActive={false}
                  />
                );
              })}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-slate-500">{describeTyreAgePlot(plot)}</p>
      <DriverLegend drivers={codes} styles={styles} selection={selection} mark="dot" />
      {fits.total ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            <span className="font-semibold text-slate-300">
              {fits.shown.length === fits.total
                ? `${fits.total} stint ${fits.total === 1 ? "fit" : "fits"} for the drivers shown`
                : `${fits.shown.length} of ${fits.total} stint fits for the drivers shown`}
            </span>
            {fits.total > FIT_PREVIEW_COUNT ? (
              <button
                type="button"
                className="rounded border border-line px-2 py-0.5 text-xs text-slate-300 transition hover:border-slate-500"
                onClick={() => setShowAllFits((current) => !current)}
              >
                {showAllFits ? "Show fewer" : `Show all ${fits.total}`}
              </button>
            ) : null}
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {fits.shown.map((row) => (
              <div key={`${row.driver_code}-${row.stint}-${row.compound}`} className="rounded border border-line bg-white/[0.03] p-3">
                <div className="font-mono text-sm font-bold text-white">{row.driver_code} S{row.stint}</div>
                <div className="mt-1 text-xs text-slate-400">{row.compound}</div>
                <div className="mt-2 text-lg font-black text-aqua">
                  {row.degradation_ms_per_lap === null || row.degradation_ms_per_lap === undefined
                    ? "--"
                    : `${row.degradation_ms_per_lap} ms/lap`}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TyreAgeTooltip({ active, payload }: TooltipContentProps) {
  const point: unknown = payload?.[0]?.payload;
  if (!active || !isTyreAgePoint(point)) {
    return null;
  }
  return (
    <div className="rounded px-3 py-2 text-xs" style={CHART_TOOLTIP_STYLE}>
      <div className="font-mono font-bold text-white">
        {point.driver_code} · lap {point.lap_number}
      </div>
      <div className="mt-1 font-mono">{formatMs(point.lap_time_ms)}</div>
      <div className="mt-1 text-slate-400">
        {point.compound ?? "Unknown compound"} · tyre age {point.tyre_age}
      </div>
    </div>
  );
}
