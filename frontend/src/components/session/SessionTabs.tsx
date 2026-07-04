"use client";

import { useState } from "react";

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
import { TelemetryComparePanel } from "@/components/telemetry/TelemetryComparePanel";
import { formatDelta, formatMs } from "@/lib/format";
import { isEmptyState } from "@/lib/api";
import type {
  ChartSeries,
  Driver,
  Lap,
  PitStop,
  PositionReplayFrame,
  RaceControlMessage,
  RacePaceResult,
  Result,
  SessionSummary,
  Stint,
  TelemetryComparison,
  TyreDegradationResult,
  WeatherSample,
  EmptyStateResponse
} from "@/types/domain";

const tabs = [
  "Overview",
  "Lap Times",
  "Race Pace",
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
  positionReplay: PositionReplayFrame[] | EmptyStateResponse;
};

export function SessionTabs(props: SessionTabsProps) {
  const [active, setActive] = useState(tabs[0]);
  return (
    <div className="space-y-5">
      <div className="overflow-x-auto rounded border border-line bg-panel p-1">
        <div className="flex min-w-max gap-1">
          {tabs.map((tab) => (
            <button
              key={tab}
              className={`rounded px-3 py-2 text-sm font-semibold ${
                active === tab ? "bg-redline text-white" : "text-slate-400 hover:bg-white/[0.05] hover:text-white"
              }`}
              onClick={() => setActive(tab)}
              type="button"
            >
              {tab}
            </button>
          ))}
        </div>
      </div>
      {active === "Overview" ? <Overview {...props} /> : null}
      {active === "Lap Times" ? (
        <ChartPanel title="Lap Time Evolution" description="All available lap times by driver.">
          <LapTimeChart series={props.lapTimes} />
        </ChartPanel>
      ) : null}
      {active === "Race Pace" ? <RacePaceView {...props} /> : null}
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
        rows={laps.slice(0, 12)}
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

function RacePaceView({ racePace, tyreDegradation, laps }: SessionTabsProps) {
  return (
    <div className="space-y-5">
      <ChartPanel title="Driver Race Pace" description={racePace.caveats.join(" ")}>
        <RacePaceChart rows={racePace.drivers} />
      </ChartPanel>
      <ChartPanel title="Tyre Degradation" description="Clean laps plotted by tyre age with fitted slope summaries.">
        <TyreDegradationChart laps={laps} degradation={tyreDegradation} />
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
    </div>
  );
}

function StrategyView({ stints, pitStops }: SessionTabsProps) {
  return (
    <div className="space-y-5">
      <ChartPanel title="Stint Timeline">
        <StintTimeline stints={stints} />
      </ChartPanel>
      <ChartPanel title="Pit Stop Timeline">
        <PitStopTimeline stops={pitStops} />
      </ChartPanel>
    </div>
  );
}

function TelemetryView({ telemetryComparison, summary }: SessionTabsProps) {
  if (isEmptyState(telemetryComparison)) {
    return (
      <EmptyState
        title="Telemetry unavailable"
        detail={[telemetryComparison.reason, telemetryComparison.action].filter(Boolean).join(" ")}
      />
    );
  }
  return <TelemetryComparePanel sessionId={summary.session_id} initialComparison={telemetryComparison} />;
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
  const colors = Object.fromEntries(drivers.map((driver) => [driver.code, driver.team.color]));
  return (
    <DataTable
      rows={results}
      columns={[
        { key: "pos", header: "Pos", align: "right", render: (row) => row.position },
        { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
        { key: "grid", header: "Grid", align: "right", render: (row) => row.grid ?? "--" },
        { key: "gap", header: "Gap", align: "right", render: (row) => row.gap || "--" },
        { key: "status", header: "Status", render: (row) => row.status || "--" },
        { key: "points", header: "Pts", align: "right", render: (row) => row.points ?? 0 }
      ]}
    />
  );
}

