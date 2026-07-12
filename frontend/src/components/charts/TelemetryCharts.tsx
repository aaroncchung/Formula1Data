"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import { telemetryRows } from "@/lib/chart-utils";
import { formatDelta, formatMs, formatNumber } from "@/lib/format";
import type { TelemetryComparison } from "@/types/domain";

const DRIVER_A = "#f33d3d";
const DRIVER_B = "#2de0c8";

type TelemetryChartDef = {
  keyA: string;
  keyB?: string;
  title: string;
  unit: string;
  domain?: [number, number];
};

const chartDefs: TelemetryChartDef[] = [
  { keyA: "deltaTime", title: "Cumulative lap delta", unit: "ms", domain: undefined },
  { keyA: "speedA", keyB: "speedB", title: "Speed", unit: "km/h", domain: undefined },
  { keyA: "throttleA", keyB: "throttleB", title: "Throttle", unit: "%", domain: [0, 100] },
  { keyA: "brakeA", keyB: "brakeB", title: "Brake application", unit: "", domain: [0, 1] },
  { keyA: "gearA", keyB: "gearB", title: "Gear", unit: "", domain: [0, 8] },
  { keyA: "rpmA", keyB: "rpmB", title: "Engine speed", unit: "rpm", domain: undefined }
];

export function TelemetryCharts({ comparison }: { comparison: TelemetryComparison }) {
  const rows = telemetryRows(comparison);
  const lapDelta = lapTimeDelta(comparison);
  const maxSpeedA = max(comparison.speed_a);
  const maxSpeedB = max(comparison.speed_b);
  const fullThrottleA = percentage(comparison.throttle_a, (value) => value >= 98);
  const fullThrottleB = percentage(comparison.throttle_b, (value) => value >= 98);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ComparisonMetric
          label="Lap time"
          a={formatMs(comparison.driver_a.lap_time_ms)}
          b={formatMs(comparison.driver_b.lap_time_ms)}
          footer={`${comparison.driver_b.driver_code} ${formatDelta(lapDelta)}`}
        />
        <ComparisonMetric
          label="Maximum speed"
          a={`${formatNumber(maxSpeedA, 0)} km/h`}
          b={`${formatNumber(maxSpeedB, 0)} km/h`}
          footer={`${formatNumber((maxSpeedB ?? 0) - (maxSpeedA ?? 0), 1)} km/h difference`}
        />
        <ComparisonMetric
          label="Full throttle"
          a={`${formatNumber(fullThrottleA, 1)}%`}
          b={`${formatNumber(fullThrottleB, 1)}%`}
          footer="Share of sampled lap"
        />
        <ComparisonMetric
          label="Compounds"
          a={comparison.driver_a.compound || "Unknown"}
          b={comparison.driver_b.compound || "Unknown"}
          footer="Selected lap tyre"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.65fr)]">
        <div className="space-y-3">
          {chartDefs.map((chart) => (
            <div key={chart.title} className="rounded-md border border-line/70 bg-carbon/45 p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="text-sm font-bold text-white">{chart.title}</div>
                <div className="text-[11px] uppercase tracking-wider text-slate-600">Distance</div>
              </div>
              <div className="h-[190px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={rows} syncId="telemetry-distance" margin={{ top: 5, right: 12, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="#252e3e" strokeDasharray="3 5" vertical={false} />
                    <XAxis
                      dataKey="distance"
                      stroke="#64748b"
                      tickLine={false}
                      axisLine={false}
                      minTickGap={45}
                      tickFormatter={(value) => `${(Number(value) / 1000).toFixed(1)} km`}
                    />
                    <YAxis
                      stroke="#64748b"
                      tickLine={false}
                      axisLine={false}
                      width={48}
                      domain={chart.domain ? [...chart.domain] : ["auto", "auto"]}
                    />
                    <Tooltip
                      contentStyle={{ background: "#0b1019", border: "1px solid #283246", borderRadius: 6, color: "#e5edf8" }}
                      labelFormatter={(value) => `${(Number(value) / 1000).toFixed(3)} km`}
                      formatter={(value) => `${formatNumber(Number(value), chart.unit === "ms" ? 0 : 1)}${chart.unit ? ` ${chart.unit}` : ""}`}
                    />
                    {chart.title === "Cumulative lap delta" ? <ReferenceLine y={0} stroke="#64748b" strokeDasharray="3 3" /> : <Legend />}
                    <Line
                      type="monotone"
                      dataKey={chart.keyA}
                      name={chart.keyB ? comparison.driver_a.driver_code : `${comparison.driver_b.driver_code} to ${comparison.driver_a.driver_code}`}
                      connectNulls
                      dot={false}
                      isAnimationActive={false}
                      stroke={chart.keyB ? DRIVER_A : "#f5b83d"}
                      strokeWidth={2}
                    />
                    {chart.keyB ? (
                      <Line
                        type="monotone"
                        dataKey={chart.keyB}
                        name={comparison.driver_b.driver_code}
                        connectNulls
                        dot={false}
                        isAnimationActive={false}
                        stroke={DRIVER_B}
                        strokeWidth={2}
                      />
                    ) : null}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          ))}
        </div>
        <div className="xl:sticky xl:top-24 xl:self-start">
          <TrackMap comparison={comparison} />
          {comparison.caveats.length ? (
            <div className="mt-3 rounded-md border border-amber/20 bg-amber/5 p-3 text-xs leading-5 text-slate-400">
              {comparison.caveats.join(" ")}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ComparisonMetric({ label, a, b, footer }: { label: string; a: string; b: string; footer: string }) {
  return (
    <div className="rounded-md border border-line/70 bg-carbon/45 p-3">
      <div className="eyebrow">{label}</div>
      <div className="mt-3 flex items-baseline justify-between gap-3 font-mono text-base font-bold">
        <span style={{ color: DRIVER_A }}>{a}</span>
        <span className="text-slate-600">vs</span>
        <span style={{ color: DRIVER_B }}>{b}</span>
      </div>
      <div className="mt-2 text-xs text-slate-500">{footer}</div>
    </div>
  );
}

function TrackMap({ comparison }: { comparison: TelemetryComparison }) {
  const points = (comparison.track_x || []).map((x, index) => ({ x, y: comparison.track_y?.[index] ?? null }));
  const valid = points.filter((point): point is { x: number; y: number } => point.x !== null && point.y !== null);
  if (valid.length < 2) {
    return (
      <div className="rounded-md border border-dashed border-line bg-carbon/30 p-8 text-center">
        <div className="text-sm font-bold text-white">Track trace unavailable</div>
        <p className="mt-2 text-xs leading-5 text-slate-500">Position channels were not included in these telemetry laps.</p>
      </div>
    );
  }
  const minX = Math.min(...valid.map((point) => point.x));
  const maxX = Math.max(...valid.map((point) => point.x));
  const minY = Math.min(...valid.map((point) => point.y));
  const maxY = Math.max(...valid.map((point) => point.y));
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  const normalized = valid.map((point) => `${24 + ((point.x - minX) / width) * 252},${276 - ((point.y - minY) / height) * 252}`).join(" ");
  return (
    <div className="rounded-md border border-line/70 bg-carbon/45 p-4">
      <div className="mb-3">
        <div className="text-sm font-bold text-white">Circuit trace</div>
        <div className="mt-1 text-xs text-slate-500">Selected {comparison.driver_a.driver_code} lap position channel</div>
      </div>
      <svg className="mx-auto aspect-square w-full max-w-[360px]" viewBox="0 0 300 300" role="img" aria-label="Circuit outline from selected telemetry lap">
        <polyline points={normalized} fill="none" stroke="#111827" strokeWidth="11" strokeLinejoin="round" strokeLinecap="round" />
        <polyline points={normalized} fill="none" stroke="#e5edf8" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={Number(normalized.split(" ")[0].split(",")[0])} cy={Number(normalized.split(" ")[0].split(",")[1])} r="5" fill={DRIVER_A} stroke="#fff" strokeWidth="2" />
      </svg>
      <div className="mt-2 flex items-center justify-center gap-2 text-xs text-slate-500">
        <span className="h-2 w-2 rounded-full bg-redline" /> Start / finish
      </div>
    </div>
  );
}

function max(values: Array<number | null>): number | null {
  const valid = values.filter((value): value is number => value !== null);
  return valid.length ? Math.max(...valid) : null;
}

function percentage(values: Array<number | null>, predicate: (value: number) => boolean): number | null {
  const valid = values.filter((value): value is number => value !== null);
  return valid.length ? (valid.filter(predicate).length / valid.length) * 100 : null;
}

function lapTimeDelta(comparison: TelemetryComparison): number | null {
  const a = comparison.driver_a.lap_time_ms;
  const b = comparison.driver_b.lap_time_ms;
  return a != null && b != null ? b - a : null;
}
