"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { DriverLegend, useDriverSelection } from "@/components/charts/DriverLegend";
import { CHART_TOOLTIP_STYLE, seriesToRows } from "@/lib/chart-utils";
import { visibleDrivers } from "@/lib/driver-selection";
import { driverStyle, teamDriverStyles } from "@/lib/driver-style";
import { formatMs } from "@/lib/format";
import type { Driver } from "@/lib/published/types";
import type { ChartSeries } from "@/types/domain";

export function LapTimeChart({ series, drivers }: { series: ChartSeries[]; drivers: ReadonlyArray<Driver> }) {
  const rows = useMemo(() => seriesToRows(series), [series]);
  const codes = useMemo(() => series.map((item) => item.name), [series]);
  // Styled from the session's driver list, like every other chart of the
  // session. A series the list does not name keeps the colour it came with.
  const styles = useMemo(
    () => teamDriverStyles(drivers, series.map((item) => ({ code: item.name, color: item.color }))),
    [drivers, series]
  );
  const selection = useDriverSelection(codes);
  return (
    <div className="space-y-3">
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 18, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="#293246" strokeDasharray="3 3" />
            <XAxis dataKey="lap" stroke="#94a3b8" />
            <YAxis
              stroke="#94a3b8"
              domain={["auto", "auto"]}
              tickFormatter={(value) => formatMs(Number(value))}
            />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={(value) => formatMs(Number(value))} />
            {visibleDrivers(codes, selection.hidden).map((code) => {
              const style = driverStyle(styles, code);
              return (
                <Line
                  key={code}
                  type="monotone"
                  dataKey={code}
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
      <DriverLegend drivers={codes} styles={styles} selection={selection} mark="line" />
    </div>
  );
}
