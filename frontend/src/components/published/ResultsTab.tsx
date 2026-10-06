"use client";

import { DataTable } from "@/components/data-table/DataTable";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { DriverBadge, TeamColorPill } from "@/components/session/Badges";
import { readResults } from "@/lib/published/artifacts";
import type { SessionResults } from "@/lib/published/artifacts";
import { formatResultGap, leaderLapCount } from "@/lib/results-view";

export function ResultsTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="results" name="results" read={readResults}>
      {(data) => <ResultsTable results={data.results} drivers={data.drivers} />}
    </SessionTab>
  );
}

function ResultsTable({ results, drivers }: SessionResults) {
  const byCode = new Map(drivers.map((driver) => [driver.code, driver]));
  const leaderLaps = leaderLapCount(results);
  return (
    <DataTable
      rows={results}
      emptyText="No classification was published for this session."
      columns={[
        { key: "position", header: "Pos", align: "right", render: (row) => row.position },
        {
          key: "driver",
          header: "Driver",
          render: (row) => {
            const driver = byCode.get(row.driver_code);
            return (
              <span className="inline-flex items-center gap-3">
                <DriverBadge code={row.driver_code} color={driver?.team.color} />
                {driver ? <span className="text-slate-400">{driver.full_name}</span> : null}
              </span>
            );
          }
        },
        {
          key: "team",
          header: "Team",
          render: (row) => {
            const team = byCode.get(row.driver_code)?.team;
            return team ? <TeamColorPill name={team.name} color={team.color} /> : "--";
          }
        },
        { key: "grid", header: "Grid", align: "right", render: (row) => row.grid ?? "--" },
        { key: "laps", header: "Laps", align: "right", render: (row) => row.laps ?? "--" },
        {
          key: "gap",
          header: "Time / gap",
          align: "right",
          render: (row) => <span className="font-mono">{formatResultGap(row, leaderLaps)}</span>
        },
        { key: "status", header: "Status", render: (row) => row.status || "--" },
        { key: "points", header: "Pts", align: "right", render: (row) => row.points ?? 0 }
      ]}
    />
  );
}
