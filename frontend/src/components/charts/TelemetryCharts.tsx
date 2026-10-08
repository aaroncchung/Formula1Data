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

import { CornerMarks } from "@/components/session/CornerMarks";
import { telemetryRows } from "@/lib/chart-utils";
import { circuitLayout, cornersOnLap, layoutNote, trackMap } from "@/lib/circuit-layout";
import type { CircuitLayout } from "@/lib/circuit-layout";
import { formatDelta, formatMs, formatNumber } from "@/lib/format";
import type { Corners } from "@/lib/published/types";
import type { TelemetryComparison } from "@/lib/telemetry-compare";
import type { Viewport } from "@/lib/track-map";

const DRIVER_A = "#f33d3d";
const DRIVER_B = "#2de0c8";
// The padding leaves room for a corner's label off the outside of the track.
const TRACE_VIEWPORT: Viewport = { width: 300, height: 300, padding: 30 };
const Y_AXIS_WIDTH = 62;
const CORNER_RADIUS = 6.5;
const CORNER_LABEL_DISTANCE = 15;

type TelemetryChartDef = {
  keyA: string;
  keyB?: string;
  title: string;
  unit: string;
  domain?: [number, number];
  /** Drawn as steps: the value is one thing or another, never part-way between. */
  stepped?: boolean;
  /** Marked with the circuit's corners along its distance axis. */
  corners?: boolean;
};

const CHARTS: TelemetryChartDef[] = [
  { keyA: "deltaTime", title: "Cumulative lap delta", unit: "ms" },
  { keyA: "speedA", keyB: "speedB", title: "Speed", unit: "km/h", corners: true },
  { keyA: "throttleA", keyB: "throttleB", title: "Throttle", unit: "%", domain: [0, 100] },
  { keyA: "brakeA", keyB: "brakeB", title: "Brake application", unit: "", domain: [0, 1], stepped: true },
  { keyA: "gearA", keyB: "gearB", title: "Gear", unit: "", domain: [0, 8], stepped: true },
  { keyA: "rpmA", keyB: "rpmB", title: "Engine speed", unit: "rpm" }
];

// Only for a session published with the channel: 2026 has no DRS, and its
// laps carry none.
const DRS_CHART: TelemetryChartDef = { keyA: "drsA", keyB: "drsB", title: "DRS open", unit: "", domain: [0, 1], stepped: true };

/**
 * `corners` is the circuit's own corner map, or null when the session has
 * none. Where it fits the track, the trace is turned the way F1 draws the
 * circuit with its corners numbered, and the speed chart marks where along
 * the lap each corner is.
 */
export function TelemetryCharts({ comparison, corners }: { comparison: TelemetryComparison; corners: Corners | null }) {
  const rows = telemetryRows(comparison);
  const layout = circuitLayout(corners);
  // The distance axis is lap A's own, so the corners are marked where lap A passes them.
  const alongLap = cornersOnLap(layout, comparison.track, comparison.whole_a);
  const charts = comparison.drs_a || comparison.drs_b ? [...CHARTS, DRS_CHART] : CHARTS;
  const lapDelta = lapTimeDelta(comparison);
  // Each lap's own figures, not lap B's as it is read at lap A's places.
  const maxSpeedA = comparison.figures_a.max_speed_kph;
  const maxSpeedB = comparison.figures_b.max_speed_kph;
  const fullThrottleA = comparison.figures_a.full_throttle_pct;
  const fullThrottleB = comparison.figures_b.full_throttle_pct;

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
          footer="Share of each lap's own samples"
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
                <div className="text-[11px] uppercase tracking-wider text-slate-600">
                  {chart.corners && alongLap.length
                    ? `Distance · numbered lines are the circuit's corners, where ${comparison.driver_a.driver_code}'s lap passes them`
                    : "Distance"}
                </div>
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
                      // Room for "-45000": two pit laps can be most of a minute apart, and a
                      // narrower axis cut the minus sign off. The same on every chart, so that
                      // one distance is at one place across them.
                      width={Y_AXIS_WIDTH}
                      domain={chart.domain ? [...chart.domain] : ["auto", "auto"]}
                    />
                    <Tooltip
                      contentStyle={{ background: "#0b1019", border: "1px solid #283246", borderRadius: 6, color: "#e5edf8" }}
                      labelFormatter={(value) => `${(Number(value) / 1000).toFixed(3)} km`}
                      formatter={(value) => `${formatNumber(Number(value), chart.unit === "ms" ? 0 : 1)}${chart.unit ? ` ${chart.unit}` : ""}`}
                    />
                    {chart.keyB ? <Legend /> : <ReferenceLine y={0} stroke="#64748b" strokeDasharray="3 3" />}
                    {chart.corners
                      ? alongLap.map((corner) => (
                          <ReferenceLine
                            key={corner.label}
                            x={corner.distance_m}
                            stroke="#334155"
                            label={{ value: corner.label, position: "insideTop", fill: "#64748b", fontSize: 10 }}
                          />
                        ))
                      : null}
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
          <TrackMap comparison={comparison} layout={layout} />
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

function TrackMap({ comparison, layout }: { comparison: TelemetryComparison; layout: CircuitLayout }) {
  const map = comparison.track.length < 2 ? null : trackMap(comparison.track, layout, TRACE_VIEWPORT, CORNER_LABEL_DISTANCE);
  if (!map) {
    return (
      <div className="rounded-md border border-dashed border-line bg-carbon/30 p-8 text-center">
        <div className="text-sm font-bold text-white">Track trace unavailable</div>
        <p className="mt-2 text-xs leading-5 text-slate-500">
          {`${comparison.driver_a.driver_code}'s lap ${comparison.driver_a.lap_number} was published without usable position data.`}
        </p>
      </div>
    );
  }
  const placed = comparison.track.map((point) => map.place(point));
  const normalized = placed.map((point) => `${point.x},${point.y}`).join(" ");
  const note = layoutNote(layout);
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
        <CornerMarks corners={map.corners} radius={CORNER_RADIUS} />
        <circle cx={placed[0].x} cy={placed[0].y} r="5" fill={DRIVER_A} stroke="#fff" strokeWidth="2" />
      </svg>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <span className="inline-flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-redline" /> Start of the lap
        </span>
        {map.corners.length ? <span>Numbered discs are the circuit&apos;s official corners</span> : null}
      </div>
      {note ? <p className="mt-2 text-center text-xs text-slate-500">{note}</p> : null}
    </div>
  );
}

function lapTimeDelta(comparison: TelemetryComparison): number | null {
  const a = comparison.driver_a.lap_time_ms;
  const b = comparison.driver_b.lap_time_ms;
  return a !== null && b !== null ? b - a : null;
}
