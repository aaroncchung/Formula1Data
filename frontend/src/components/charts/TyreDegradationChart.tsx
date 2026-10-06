"use client";

import {
  CartesianGrid,
  Legend,
  Scatter,
  ScatterChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import { CHART_TOOLTIP_STYLE } from "@/lib/chart-utils";
import { formatMs } from "@/lib/format";
import type { Lap, TyreDegradationResult } from "@/types/domain";

const colors = ["#f33d3d", "#2de0c8", "#f5b83d", "#a78bfa", "#fb7185", "#38bdf8"];

export function TyreDegradationChart({
  laps,
  degradation
}: {
  laps: Lap[];
  degradation: TyreDegradationResult;
}) {
  const byDriver = Array.from(new Set(laps.map((lap) => lap.driver_code))).slice(0, 8);
  return (
    <div className="space-y-4">
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="#293246" strokeDasharray="3 3" />
            <XAxis dataKey="tyre_age" name="Tyre age" stroke="#94a3b8" />
            <YAxis
              dataKey="lap_time_ms"
              name="Lap time"
              stroke="#94a3b8"
              tickFormatter={(value) => formatMs(Number(value))}
            />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              contentStyle={CHART_TOOLTIP_STYLE}
              formatter={(value, name) =>
                name === "lap_time_ms" ? formatMs(Number(value)) : String(value)
              }
            />
            <Legend />
            {byDriver.map((driver, index) => (
              <Scatter
                key={driver}
                name={driver}
                data={laps.filter(
                  (lap) =>
                    lap.driver_code === driver &&
                    lap.lap_time_ms &&
                    lap.tyre_age &&
                    !lap.is_pit_in_lap &&
                    !lap.is_pit_out_lap
                )}
                fill={colors[index % colors.length]}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {degradation.rows.slice(0, 6).map((row) => (
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
  );
}

