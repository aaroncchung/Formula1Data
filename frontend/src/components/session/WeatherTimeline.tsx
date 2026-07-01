"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { WeatherSample } from "@/types/domain";

export function WeatherTimeline({ samples }: { samples: WeatherSample[] }) {
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={samples}>
          <CartesianGrid stroke="#293246" strokeDasharray="3 3" />
          <XAxis dataKey="lap_number" stroke="#94a3b8" />
          <YAxis stroke="#94a3b8" />
          <Tooltip contentStyle={{ background: "#111722", border: "1px solid #283246", color: "#e5edf8" }} />
          <Line type="monotone" dataKey="air_temp_c" name="Air C" stroke="#2de0c8" strokeWidth={2} />
          <Line type="monotone" dataKey="track_temp_c" name="Track C" stroke="#f33d3d" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

