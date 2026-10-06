"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { DriverLegend, useDriverSelection } from "@/components/charts/DriverLegend";
import { CHART_TOOLTIP_STYLE, seriesToRows } from "@/lib/chart-utils";
import { visibleDrivers } from "@/lib/driver-selection";
import { assignDriverStyles, driverStyle } from "@/lib/driver-style";
import { formatMs } from "@/lib/format";
import type { ChartSeries } from "@/types/domain";

export function LapTimeChart({ series }: { series: ChartSeries[] }) {
  const rows = useMemo(() => seriesToRows(series), [series]);
  const drivers = useMemo(() => series.map((item) => item.name), [series]);
  const styles = useMemo(
    () => assignDriverStyles(series.map((item) => ({ code: item.name, color: item.color }))),
    [series]
  );
  const selection = useDriverSelection(drivers);
  return (
    <div className="space-y-3">
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 18, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="#293246" strokeDasharray="3 3" />
            <XAxis dataKey="lap" stroke="#94a3b8" />
            <YAxis stroke="#94a3b8" tickFormatter={(value) => formatMs(Number(value))} />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={(value) => formatMs(Number(value))} />
            {visibleDrivers(drivers, selection.hidden).map((driver) => {
              const style = driverStyle(styles, driver);
              return (
                <Line
                  key={driver}
                  type="monotone"
                  dataKey={driver}
                  dot={false}
                  stroke={style.color}
                  strokeDasharray={style.dash}
                  strokeWidth={2}
                  connectNulls
                  isAnimationActive={false}
                />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <DriverLegend drivers={drivers} styles={styles} selection={selection} mark="line" />
    </div>
  );
}
