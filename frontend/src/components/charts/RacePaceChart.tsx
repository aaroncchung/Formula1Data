"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatDelta, formatMs } from "@/lib/format";
import type { RacePaceRow } from "@/types/domain";

export function RacePaceChart({ rows }: { rows: RacePaceRow[] }) {
  const data = rows.map((row) => ({
    driver: row.driver_code,
    median: row.median_lap_ms,
    gap: row.gap_to_best_ms
  }));
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
          <CartesianGrid stroke="#293246" strokeDasharray="3 3" />
          <XAxis dataKey="driver" stroke="#94a3b8" />
          <YAxis stroke="#94a3b8" tickFormatter={(value) => formatMs(Number(value))} />
          <Tooltip
            contentStyle={{ background: "#111722", border: "1px solid #283246", color: "#e5edf8" }}
            formatter={(value, name) =>
              name === "gap" ? formatDelta(Number(value)) : formatMs(Number(value))
            }
          />
          <Bar dataKey="median" fill="#f33d3d" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

