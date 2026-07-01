"use client";

import { useMemo, useState } from "react";
import { Scatter, ScatterChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { PositionReplayFrame } from "@/types/domain";

export function PositionReplay({ frames }: { frames: PositionReplayFrame[] }) {
  const [index, setIndex] = useState(0);
  const frame = frames[index] || frames[0];
  const data = useMemo(
    () =>
      (frame?.positions || []).map((position) => ({
        ...position,
        x: Number(position.x),
        y: Number(position.y)
      })),
    [frame]
  );
  if (!frame) {
    return <div className="text-sm text-slate-400">No replay frames available.</div>;
  }
  return (
    <div className="space-y-4">
      <div className="h-80 rounded border border-line bg-white/[0.03]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
            <XAxis dataKey="x" type="number" stroke="#94a3b8" hide />
            <YAxis dataKey="y" type="number" stroke="#94a3b8" hide />
            <Tooltip
              contentStyle={{ background: "#111722", border: "1px solid #283246", color: "#e5edf8" }}
              cursor={{ strokeDasharray: "3 3" }}
            />
            <Scatter data={data} fill="#f33d3d" name="Cars" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center gap-3">
        <input
          className="w-full accent-redline"
          type="range"
          min={0}
          max={Math.max(frames.length - 1, 0)}
          value={index}
          onChange={(event) => setIndex(Number(event.target.value))}
        />
        <div className="w-24 text-right font-mono text-sm text-slate-400">
          {index + 1}/{frames.length}
        </div>
      </div>
    </div>
  );
}

