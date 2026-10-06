"use client";

import { useEffect, useState } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { LapTimeChart } from "@/components/charts/LapTimeChart";
import { RacePaceChart } from "@/components/charts/RacePaceChart";
import { TyreDegradationChart } from "@/components/charts/TyreDegradationChart";
import { DataTable } from "@/components/data-table/DataTable";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { MetricCard } from "@/components/dashboard/MetricCard";
import { DriverBadge, CompoundBadge, TeamColorPill } from "@/components/session/Badges";
import { PitStopTimeline } from "@/components/session/PitStopTimeline";
import { PositionReplay } from "@/components/session/PositionReplay";
import { RaceControlFeed } from "@/components/session/RaceControlFeed";
import { StintTimeline } from "@/components/session/StintTimeline";
import { WeatherTimeline } from "@/components/session/WeatherTimeline";
import { PerformanceAnalysis } from "@/components/session/PerformanceAnalysis";
import { StrategyAnalysis } from "@/components/session/StrategyAnalysis";
import { TelemetryComparePanel } from "@/components/telemetry/TelemetryComparePanel";
import { teamColorByDriver } from "@/lib/driver-style";
import { formatDelta, formatMs, formatNumber } from "@/lib/format";
import { isEmptyState } from "@/lib/api";
import type { TelemetryIndex } from "@/lib/static-api-core";
import type {
  CarPerformanceResult,
  ChartSeries,
  CornerAnalysisResult,
  Driver,
  Lap,
  IdealLapsResult,
  PacePredictionResult,
  PitStop,
  PositionReplayFrame,
  RaceControlMessage,
  RacePaceResult,
  Result,
  SessionSummary,
  Stint,
  StrategyResult,
  TeammateComparisonResult,
  TelemetryComparison,
  TrackDominanceResult,
  TyreDegradationResult,
  WeatherSample,
  EmptyStateResponse
} from "@/types/domain";

const tabs = [
  "Overview",
  "Lap Times",
  "Race Pace",
  "Performance",
  "Strategy",
  "Telemetry",
  "Position Replay",
  "Weather",
  "Race Control",
  "Results"
];

export type SessionTabsProps = {
  summary: SessionSummary;
  drivers: Driver[];
  laps: Lap[];
  lapTimes: ChartSeries[];
  racePace: RacePaceResult;
  tyreDegradation: TyreDegradationResult;
  stints: Stint[];
  pitStops: PitStop[];
  weather: WeatherSample[];
  raceControl: RaceControlMessage[];
  results: Result[];
  telemetryComparison: TelemetryComparison | EmptyStateResponse;
  telemetryIndex: TelemetryIndex | null;
  positionReplay: PositionReplayFrame[] | EmptyStateResponse;
  idealLaps: IdealLapsResult | null;
  teammateComparison: TeammateComparisonResult | null;
  strategy: StrategyResult | null;
  trackDominance: TrackDominanceResult | null;
  cornerAnalysis: CornerAnalysisResult | null;
  carPerformance: CarPerformanceResult | null;
  pacePrediction: PacePredictionResult | null;
};

export function SessionTabs(props: SessionTabsProps) {
  const [active, setActive] = useState(tabs[0]);
  useEffect(() => {
    const requested = decodeURIComponent(window.location.hash.slice(1)).replaceAll("-", " ").toLowerCase();
    const matched = tabs.find((tab) => tab.toLowerCase() === requested);
    const frame = window.requestAnimationFrame(() => {
      if (matched) setActive(matched);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  function selectTab(tab: string) {
    setActive(tab);
    const hash = tab.toLowerCase().replaceAll(" ", "-");
    window.history.replaceState(null, "", `${window.location.pathname}#${hash}`);
  }
  return (
    <div className="space-y-5">
      <div className="surface overflow-x-auto p-1">
        <div className="flex min-w-max gap-1" role="tablist" aria-label="Session analysis views">
          {tabs.map((tab) => (
            <button
              key={tab}
              className={`rounded px-3 py-2 text-sm font-semibold ${
                active === tab ? "bg-redline text-white" : "text-slate-400 hover:bg-white/[0.05] hover:text-white"
              }`}
              onClick={() => selectTab(tab)}
              type="button"
              role="tab"
              aria-selected={active === tab}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>
      {active === "Overview" ? <Overview {...props} /> : null}
      {active === "Lap Times" ? (
        <ChartPanel title="Lap Time Evolution" description="All available lap times by driver.">
          <LapTimeChart series={props.lapTimes} drivers={props.drivers} />
        </ChartPanel>
      ) : null}
      {active === "Race Pace" ? <RacePaceView {...props} /> : null}
      {active === "Performance" ? (
        <PerformanceAnalysis
          drivers={props.drivers}
          idealLaps={props.idealLaps || null}
          teammateComparison={props.teammateComparison || null}
          trackDominance={props.trackDominance || null}
          cornerAnalysis={props.cornerAnalysis || null}
          carPerformance={props.carPerformance || null}
          pacePrediction={props.pacePrediction || null}
        />
      ) : null}
      {active === "Strategy" ? <StrategyView {...props} /> : null}
      {active === "Telemetry" ? <TelemetryView {...props} /> : null}
      {active === "Position Replay" ? <ReplayView {...props} /> : null}
      {active === "Weather" ? (
        <ChartPanel title="Weather Timeline">
          <WeatherTimeline samples={props.weather} />
        </ChartPanel>
      ) : null}
      {active === "Race Control" ? (
        <ChartPanel title="Race Control Feed">
          <RaceControlFeed messages={props.raceControl} />
        </ChartPanel>
      ) : null}
      {active === "Results" ? <ResultsView results={props.results} drivers={props.drivers} /> : null}
    </div>
  );
}

function Overview({ summary, drivers, laps, racePace, stints, pitStops }: SessionTabsProps) {
  const fastestLaps = drivers
    .map((driver) => laps.filter((lap) => lap.driver_code === driver.code && lap.lap_time_ms != null && !lap.is_deleted)
      .sort((a, b) => Number(a.lap_time_ms) - Number(b.lap_time_ms))[0])
    .filter((lap): lap is Lap => Boolean(lap))
    .sort((a, b) => Number(a.lap_time_ms) - Number(b.lap_time_ms));
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Drivers" value={summary.driver_count} detail="classified in artifact" tone="aqua" />
        <MetricCard label="Laps" value={summary.lap_count} detail="normalized timing rows" tone="red" />
        <MetricCard label="Stints" value={stints.length} detail="compound runs" tone="amber" />
        <MetricCard label="Pit stops" value={pitStops.length} detail="strategy events" />
      </div>
      {summary.is_sample ? (
        <EmptyState
          title="Demo mode"
          detail="This session is synthetic sample data. Run the ingest script to replace it with FastF1/OpenF1 artifacts."
        />
      ) : null}
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <ChartPanel title="Race Pace Snapshot">
          <RacePaceChart rows={racePace.drivers} />
        </ChartPanel>
        <ChartPanel title="Driver Roster">
          <div className="space-y-3">
            {drivers.map((driver) => (
              <div key={driver.code} className="flex items-center justify-between gap-3 rounded border border-line bg-white/[0.03] p-3">
                <DriverBadge code={driver.code} color={driver.team.color} />
                <TeamColorPill name={driver.team.name} color={driver.team.color} />
              </div>
            ))}
          </div>
        </ChartPanel>
      </div>
      <DataTable
        rows={fastestLaps}
        columns={[
          { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} /> },
          { key: "lap", header: "Lap", align: "right", render: (row) => row.lap_number },
          { key: "time", header: "Lap Time", align: "right", render: (row) => formatMs(row.lap_time_ms) },
          { key: "compound", header: "Compound", render: (row) => <CompoundBadge compound={row.compound} /> }
        ]}
      />
    </div>
  );
}

function RacePaceView({ racePace, tyreDegradation, laps, drivers }: SessionTabsProps) {
  return (
    <div className="space-y-5">
      <ChartPanel title="Driver Race Pace" description={racePace.caveats.join(" ")}>
        <RacePaceChart rows={racePace.drivers} />
      </ChartPanel>
      <ChartPanel title="Tyre Degradation" description="Lap time against tyre age for every driver, with the fitted slope of each stint.">
        <TyreDegradationChart laps={laps} degradation={tyreDegradation} drivers={drivers} />
      </ChartPanel>
      <DataTable
        rows={racePace.drivers}
        columns={[
          { key: "driver", header: "Driver", render: (row) => row.driver_code },
          { key: "median", header: "Median", align: "right", render: (row) => formatMs(row.median_lap_ms) },
          { key: "trimmed", header: "Trimmed", align: "right", render: (row) => formatMs(row.trimmed_mean_lap_ms) },
          { key: "fastest", header: "Fastest", align: "right", render: (row) => formatMs(row.fastest_clean_lap_ms) },
          { key: "gap", header: "Gap", align: "right", render: (row) => formatDelta(row.gap_to_best_ms) }
        ]}
      />
      <div>
        <div className="mb-3">
          <h3 className="font-bold text-white">Degradation model</h3>
          <p className="mt-1 text-sm text-slate-500">Raw fitted slope, fuel correction, and the adjusted tyre trend used by the analysis.</p>
        </div>
        <DataTable
          rows={tyreDegradation.rows}
          emptyText="No qualifying tyre stints were available."
          columns={[
            { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} /> },
            { key: "compound", header: "Compound", render: (row) => <CompoundBadge compound={row.compound} /> },
            { key: "stint", header: "Stint", align: "right", render: (row) => row.stint },
            { key: "raw", header: "Raw slope", align: "right", render: (row) => `${formatNumber(row.raw_slope_ms_per_lap, 1)} ms/lap` },
            { key: "fuel", header: "Fuel correction", align: "right", render: (row) => `${formatNumber(row.fuel_correction_ms_per_lap, 1)} ms/lap` },
            { key: "adjusted", header: "Adjusted", align: "right", render: (row) => `${formatNumber(row.degradation_ms_per_lap, 1)} ms/lap` },
            { key: "fit", header: "R²", align: "right", render: (row) => formatNumber(row.r_squared, 2) },
            { key: "excluded", header: "Outliers", align: "right", render: (row) => row.excluded_outlier_count ?? 0 }
          ]}
        />
      </div>
    </div>
  );
}

function StrategyView({ stints, pitStops, strategy }: SessionTabsProps) {
  return (
    <div className="space-y-5">
      <ChartPanel title="Stint Timeline">
        <StintTimeline stints={stints} />
      </ChartPanel>
      <ChartPanel title="Pit Stop Timeline">
        <PitStopTimeline stops={pitStops} />
      </ChartPanel>
      <ChartPanel title="Strategy Analysis" description="Compound usage, pit-lane timing, and post-stop pace estimates.">
        <StrategyAnalysis strategy={strategy || null} pitStops={pitStops} />
      </ChartPanel>
    </div>
  );
}

function TelemetryView({ telemetryComparison, telemetryIndex, summary }: SessionTabsProps) {
  if (isEmptyState(telemetryComparison)) {
    return (
      <EmptyState
        title="Telemetry unavailable"
        detail={[telemetryComparison.reason, telemetryComparison.action].filter(Boolean).join(" ")}
      />
    );
  }
  return <TelemetryComparePanel sessionId={summary.session_id} initialComparison={telemetryComparison} availableLaps={telemetryIndex?.laps || []} />;
}

function ReplayView({ positionReplay }: SessionTabsProps) {
  if (isEmptyState(positionReplay)) {
    return <EmptyState title="Position replay unavailable" detail={positionReplay.reason} />;
  }
  return (
    <ChartPanel title="Position Replay" description="Frame-based x/y replay from location telemetry.">
      <PositionReplay frames={positionReplay} />
    </ChartPanel>
  );
}

function ResultsView({ results, drivers }: { results: Result[]; drivers: Driver[] }) {
  const colors = teamColorByDriver(drivers);
  return (
    <DataTable
      rows={results}
      columns={[
        { key: "pos", header: "Pos", align: "right", render: (row) => row.position },
        { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
        { key: "grid", header: "Grid", align: "right", render: (row) => row.grid ?? "--" },
          { key: "gap", header: "Gap", align: "right", render: (row) => formatResultGap(row) },
        { key: "status", header: "Status", render: (row) => row.status || "--" },
        { key: "points", header: "Pts", align: "right", render: (row) => row.points ?? 0 }
      ]}
    />
  );
}

function formatResultGap(result: Result) {
  if (result.position === 1) return "Winner";
  if (!result.gap || result.gap === "NaT") return "--";
  const match = result.gap.match(/(\d+):(\d+):(\d+(?:\.\d+)?)/);
  if (!match) return result.gap;
  const seconds = Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
  return `+${seconds.toFixed(3)}s`;
}

