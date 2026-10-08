"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { RacePaceChart } from "@/components/charts/RacePaceChart";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { MetricCard } from "@/components/dashboard/MetricCard";
import { DataTable } from "@/components/data-table/DataTable";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { CompoundBadge, DriverBadge, TeamColorPill } from "@/components/session/Badges";
import { teamColorByDriver } from "@/lib/driver-style";
import { formatMs } from "@/lib/format";
import { fastestLapByDriver } from "@/lib/lap-summary";
import { readOverview, type SessionOverview } from "@/lib/published/artifacts";
import { pitEntryCounts } from "@/lib/strategy-view";

export function OverviewTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="overview" name="overview" read={readOverview}>
      {(data) => <Overview {...data} />}
    </SessionTab>
  );
}

function Overview({ summary, drivers, laps, racePace, stints, pitStops }: SessionOverview) {
  const colors = teamColorByDriver(drivers);
  const where = [summary.circuit, summary.country].filter(Boolean).join(", ");
  // Not every entry to the pit lane is a pit stop: a car can drive through.
  const pitCounts = pitEntryCounts(pitStops);
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Drivers" value={summary.driver_count} detail="in the session" tone="aqua" />
        <MetricCard label="Laps" value={summary.lap_count} detail="across all drivers" tone="red" />
        <MetricCard label="Stints" value={stints.length} detail="runs on one set of tyres" tone="amber" />
        <MetricCard
          label="Pit stops"
          value={pitCounts.stops}
          detail={pitCounts.stops === pitCounts.entries ? "detected" : `of ${pitCounts.entries} entries to the pit lane`}
        />
      </div>
      {where || summary.weather_summary ? (
        <p className="text-sm text-slate-400">
          {[where, summary.weather_summary ? `Conditions: ${summary.weather_summary}` : ""].filter(Boolean).join(" · ")}
        </p>
      ) : null}
      {summary.is_sample ? (
        <EmptyState title="Sample data" detail="This session is synthetic sample data, not a session that was run." />
      ) : null}
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <ChartPanel title="Race Pace Snapshot" description="Median clean lap of each driver.">
          <RacePaceChart rows={racePace.drivers} />
        </ChartPanel>
        <ChartPanel title="Driver Roster">
          <div className="space-y-3">
            {drivers.map((driver) => (
              <div key={driver.code} className="flex items-center justify-between gap-3 rounded border border-line bg-white/[0.03] p-3">
                <DriverBadge code={driver.code} color={driver.team?.color} />
                {driver.team ? (
                  <TeamColorPill name={driver.team.name} color={driver.team.color} />
                ) : (
                  <span className="text-xs text-slate-500">No team listed</span>
                )}
              </div>
            ))}
          </div>
        </ChartPanel>
      </div>
      <div>
        <h3 className="mb-3 font-bold text-white">Fastest lap of each driver</h3>
        <DataTable
          rows={fastestLapByDriver(laps)}
          emptyText="No timed laps in this session."
          columns={[
            { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
            { key: "lap", header: "Lap", align: "right", render: (row) => row.lap_number },
            { key: "time", header: "Lap Time", align: "right", render: (row) => formatMs(row.lap_time_ms) },
            { key: "compound", header: "Compound", render: (row) => <CompoundBadge compound={row.compound} /> }
          ]}
        />
      </div>
    </div>
  );
}
