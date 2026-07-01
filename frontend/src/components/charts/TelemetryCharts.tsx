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

import { telemetryRows } from "@/lib/chart-utils";
import type { TelemetryComparison } from "@/types/domain";

const chartDefs = [
  { keyA: "speedA", keyB: "speedB", title: "Speed", unit: "kph" },
  { keyA: "throttleA", keyB: "throttleB", title: "Throttle", unit: "%" },
  { keyA: "brakeA", keyB: "brakeB", title: "Brake", unit: "" },
  { keyA: "rpmA", keyB: "rpmB", title: "RPM", unit: "" },
  { keyA: "gearA", keyB: "gearB", title: "Gear", unit: "" },
  { keyA: "drsA", keyB: "drsB", title: "DRS", unit: "" },
  { keyA: "delta", keyB: undefined, title: "Speed Delta", unit: "kph" }
];

export function TelemetryCharts({ comparison }: { comparison: TelemetryComparison }) {
  const rows = telemetryRows(comparison);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {chartDefs.map((chart) => (
        <div key={chart.title} className="h-64 rounded border border-line bg-white/[0.03] p-3">
          <div className="mb-2 text-sm font-bold text-white">{chart.title}</div>
          <ResponsiveContainer width="100%" height="85%">
            <LineChart data={rows}>
              <CartesianGrid stroke="#293246" strokeDasharray="3 3" />
              <XAxis dataKey="distance" stroke="#94a3b8" tickFormatter={(value) => `${Number(value) / 1000}k`} />
              <YAxis stroke="#94a3b8" />
              <Tooltip
                contentStyle={{ background: "#111722", border: "1px solid #283246", color: "#e5edf8" }}
                formatter={(value) => `${value}${chart.unit ? ` ${chart.unit}` : ""}`}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey={chart.keyA}
                name={chart.keyB ? comparison.driver_a.driver_code : "Delta"}
                dot={false}
                stroke={chart.keyB ? "#f33d3d" : "#f5b83d"}
                strokeWidth={2}
              />
              {chart.keyB ? (
                <Line
                  type="monotone"
                  dataKey={chart.keyB}
                  name={comparison.driver_b.driver_code}
                  dot={false}
                  stroke="#2de0c8"
                  strokeWidth={2}
                />
              ) : null}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ))}
    </div>
  );
}

