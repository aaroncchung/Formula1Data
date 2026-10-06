"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { CHART_TOOLTIP_STYLE } from "@/lib/chart-utils";
import { formatSessionClock, formatSessionClockMinutes } from "@/lib/pandas-time";
import { describeWeatherPlot, sessionClockTicks, weatherPlot } from "@/lib/weather-chart";
import type { WeatherSample } from "@/types/domain";

const AIR = "#2de0c8";
const TRACK = "#f33d3d";

/**
 * Air and track temperature through the session, against the session clock.
 * The samples carry no lap number, so there is no lap axis to draw.
 */
export function WeatherTimeline({ samples }: { samples: WeatherSample[] }) {
  const plot = useMemo(() => weatherPlot(samples), [samples]);
  const ticks = useMemo(() => {
    const first = plot.points[0];
    const last = plot.points[plot.points.length - 1];
    return first && last ? sessionClockTicks(first.time_ms, last.time_ms) : [];
  }, [plot]);

  if (plot.points.length === 0) {
    return <p className="text-sm text-slate-400">{describeWeatherPlot(plot)}</p>;
  }
  const caption = `${describeWeatherPlot(plot)} The horizontal axis is the session clock in hours and minutes, which starts with F1's timing feed and not with the session.`;
  return (
    <div className="space-y-3">
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={plot.points} margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="#293246" strokeDasharray="3 3" />
            <XAxis
              dataKey="time_ms"
              type="number"
              domain={["dataMin", "dataMax"]}
              ticks={ticks}
              stroke="#94a3b8"
              tickFormatter={(value) => formatSessionClockMinutes(Number(value))}
            />
            <YAxis stroke="#94a3b8" domain={["auto", "auto"]} tickFormatter={(value) => `${value}°C`} />
            <Tooltip
              contentStyle={CHART_TOOLTIP_STYLE}
              labelFormatter={(value) => `Session clock ${formatSessionClock(Number(value))}`}
              formatter={(value) => `${value}°C`}
            />
            {/* Straight lines between marked samples: a sample is taken every few minutes, and a curve would draw readings nobody took. */}
            <Line type="linear" dataKey="air_temp_c" name="Air" stroke={AIR} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
            <Line type="linear" dataKey="track_temp_c" name="Track" stroke={TRACK} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-400">
        <LegendEntry color={AIR} label="Air temperature" />
        <LegendEntry color={TRACK} label="Track temperature" />
      </div>
      <p className="text-xs text-slate-500">{caption}</p>
    </div>
  );
}

function LegendEntry({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-0.5 w-5 rounded" style={{ backgroundColor: color }} aria-hidden="true" />
      {label}
    </span>
  );
}
