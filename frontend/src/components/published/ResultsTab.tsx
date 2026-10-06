"use client";

import { DataTable } from "@/components/data-table/DataTable";
import { ArtifactPanel } from "@/components/published/ArtifactPanel";
import { usePublishedArtifact } from "@/components/published/usePublishedArtifact";
import { DriverBadge, TeamColorPill } from "@/components/session/Badges";
import { readResults } from "@/lib/published/artifacts";
import type { SessionResults } from "@/lib/published/artifacts";
import type { SessionView } from "@/lib/published/client";

export function ResultsTab({ view, active }: { view: SessionView; active: boolean }) {
  const { artifact, retry } = usePublishedArtifact(view, readResults);
  if (!active) {
    return null;
  }
  return (
    <ArtifactPanel tab="results" name="results" artifact={artifact} onRetry={retry}>
      {(data) => <ResultsTable results={data.results} drivers={data.drivers} />}
    </ArtifactPanel>
  );
}

function ResultsTable({ results, drivers }: SessionResults) {
  const byCode = new Map(drivers.map((driver) => [driver.code, driver]));
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
        { key: "status", header: "Status", render: (row) => row.status || "--" },
        { key: "points", header: "Pts", align: "right", render: (row) => row.points ?? 0 }
      ]}
    />
  );
}
