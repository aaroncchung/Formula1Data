"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import { CHART_TOOLTIP_STYLE, seriesToRows } from "@/lib/chart-utils";
import { formatMs } from "@/lib/format";
import type { ChartSeries } from "@/types/domain";

export function LapTimeChart({ series }: { series: ChartSeries[] }) {
  const rows = seriesToRows(series);
  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 18, left: 8, bottom: 8 }}>
          <CartesianGrid stroke="#293246" strokeDasharray="3 3" />
          <XAxis dataKey="lap" stroke="#94a3b8" />
          <YAxis stroke="#94a3b8" tickFormatter={(value) => formatMs(Number(value))} />
          <Tooltip
            contentStyle={CHART_TOOLTIP_STYLE}
            formatter={(value) => formatMs(Number(value))}
          />
          <Legend />
          {series.map((item) => (
            <Line
              key={item.name}
              type="monotone"
              dataKey={item.name}
              dot={false}
              stroke={item.color || "#94a3b8"}
              strokeWidth={2}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

