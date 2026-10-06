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
import type { TelemetryComparison } from "@/lib/telemetry-compare";
import { boundsOf, fitBounds, project, type Viewport } from "@/lib/track-map";

const DRIVER_A = "#f33d3d";
const DRIVER_B = "#2de0c8";
const TRACE_VIEWPORT: Viewport = { width: 300, height: 300, padding: 24 };

type TelemetryChartDef = {
  keyA: string;
  keyB?: string;
  title: string;
  unit: string;
  domain?: [number, number];
  /** Drawn as steps: the value is one thing or another, never part-way between. */
  stepped?: boolean;
};

const CHARTS: TelemetryChartDef[] = [
  { keyA: "deltaTime", title: "Cumulative lap delta", unit: "ms" },
  { keyA: "speedA", keyB: "speedB", title: "Speed", unit: "km/h" },
  { keyA: "throttleA", keyB: "throttleB", title: "Throttle", unit: "%", domain: [0, 100] },
  { keyA: "brakeA", keyB: "brakeB", title: "Brake application", unit: "", domain: [0, 1], stepped: true },
  { keyA: "gearA", keyB: "gearB", title: "Gear", unit: "", domain: [0, 8], stepped: true },
  { keyA: "rpmA", keyB: "rpmB", title: "Engine speed", unit: "rpm" }
];

// Only for a session published with the channel: 2026 has no DRS, and its
// laps carry none.
const DRS_CHART: TelemetryChartDef = { keyA: "drsA", keyB: "drsB", title: "DRS open", unit: "", domain: [0, 1], stepped: true };

export function TelemetryCharts({ comparison }: { comparison: TelemetryComparison }) {
  const rows = telemetryRows(comparison);
  const charts = comparison.drs_a || comparison.drs_b ? [...CHARTS, DRS_CHART] : CHARTS;
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
          footer={
            maxSpeedA === null || maxSpeedB === null
              ? "Not available for both laps"
              : `${formatNumber(maxSpeedB - maxSpeedA, 1)} km/h difference`
          }
        />
        <ComparisonMetric
          label="Full throttle"
          a={`${formatNumber(fullThrottleA, 1)}%`}
          b={`${formatNumber(fullThrottleB, 1)}%`}
          footer="Share of the samples compared"
        />
        <ComparisonMetric
          label="Compounds"
          a={comparison.driver_a.compound ?? "Unknown"}
          b={comparison.driver_b.compound ?? "Unknown"}
          footer="Selected lap tyre"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.65fr)]">
        <div className="space-y-3">
          {charts.map((chart) => (
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
                      type="number"
                      domain={["dataMin", "dataMax"]}
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
                    {chart.keyB ? <Legend /> : <ReferenceLine y={0} stroke="#64748b" strokeDasharray="3 3" />}
                    {/* Nulls are not joined: a lap has no value where its data has a hole, and a line across one would be invented. */}
                    <Line
                      type={chart.stepped ? "stepAfter" : "monotone"}
                      dataKey={chart.keyA}
                      name={chart.keyB ? comparison.driver_a.driver_code : `${comparison.driver_b.driver_code} to ${comparison.driver_a.driver_code}`}
                      dot={false}
                      isAnimationActive={false}
                      stroke={chart.keyB ? DRIVER_A : "#f5b83d"}
                      strokeWidth={2}
                    />
                    {chart.keyB ? (
                      <Line
                        type={chart.stepped ? "stepAfter" : "monotone"}
                        dataKey={chart.keyB}
                        name={comparison.driver_b.driver_code}
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
  const bounds = comparison.track.length < 2 ? null : boundsOf(comparison.track);
  if (!bounds) {
    return (
      <div className="rounded-md border border-dashed border-line bg-carbon/30 p-8 text-center">
        <div className="text-sm font-bold text-white">Track trace unavailable</div>
        <p className="mt-2 text-xs leading-5 text-slate-500">
          {comparison.driver_a.driver_code}&apos;s lap {comparison.driver_a.lap_number} was published without usable
          position data.
        </p>
      </div>
    );
  }
  const projection = fitBounds(bounds, TRACE_VIEWPORT);
  const placed = comparison.track.map((point) => project(projection, point));
  const normalized = placed.map((point) => `${point.x},${point.y}`).join(" ");
  return (
    <div className="rounded-md border border-line/70 bg-carbon/45 p-4">
      <div className="mb-3">
        <div className="text-sm font-bold text-white">Circuit trace</div>
        <div className="mt-1 text-xs text-slate-500">
          The line {comparison.driver_a.driver_code} drove on lap {comparison.driver_a.lap_number}
        </div>
      </div>
      <svg className="mx-auto aspect-square w-full max-w-[360px]" viewBox="0 0 300 300" role="img" aria-label="Circuit outline from the selected telemetry lap">
        <polyline points={normalized} fill="none" stroke="#111827" strokeWidth="11" strokeLinejoin="round" strokeLinecap="round" />
        <polyline points={normalized} fill="none" stroke="#e5edf8" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={placed[0].x} cy={placed[0].y} r="5" fill={DRIVER_A} stroke="#fff" strokeWidth="2" />
      </svg>
      <div className="mt-2 flex items-center justify-center gap-2 text-xs text-slate-500">
        <span className="h-2 w-2 rounded-full bg-redline" /> Start of the lap
      </div>
    </div>
  );
}

function max(values: ReadonlyArray<number | null>): number | null {
  const valid = values.filter((value): value is number => value !== null);
  return valid.length ? Math.max(...valid) : null;
}

function percentage(values: ReadonlyArray<number | null>, predicate: (value: number) => boolean): number | null {
  const valid = values.filter((value): value is number => value !== null);
  return valid.length ? (valid.filter(predicate).length / valid.length) * 100 : null;
}

function lapTimeDelta(comparison: TelemetryComparison): number | null {
  const a = comparison.driver_a.lap_time_ms;
  const b = comparison.driver_b.lap_time_ms;
  return a !== null && b !== null ? b - a : null;
}
