"use client";

import { DataTable } from "@/components/data-table/DataTable";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { DriverBadge, TeamColorPill } from "@/components/session/Badges";
import { readResults } from "@/lib/published/artifacts";
import type { SessionResults } from "@/lib/published/artifacts";
import { gridLabel, isProvisional, pointsLabel, resultPosition, resultTime } from "@/lib/results-view";
import type { ResultCell } from "@/lib/results-view";

export function ResultsTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="results" name="results" read={readResults}>
      {(data) => <ResultsTable results={data.results} drivers={data.drivers} />}
    </SessionTab>
  );
}

function ResultsTable({ results, drivers }: SessionResults) {
  const byCode = new Map(drivers.map((driver) => [driver.code, driver]));
  return (
    <div className="space-y-3">
      {isProvisional(results) ? (
        <p className="rounded-md border border-amber/20 bg-amber/5 p-3 text-sm text-slate-300">
          <span className="font-bold text-amber">Provisional.</span> No classification has been published for this
          session yet. This is the order on track from the timing, so it has no status, points or grid.
        </p>
      ) : null}
      <DataTable
        rows={results}
        emptyText="No classification was published for this session."
        columns={[
          { key: "position", header: "Pos", align: "right", render: (row) => <Cell cell={resultPosition(row)} /> },
          {
            key: "driver",
            header: "Driver",
            render: (row) => {
              const driver = byCode.get(row.driver_code);
              return (
                <span className="inline-flex items-center gap-3">
                  <DriverBadge code={row.driver_code} color={driver?.team?.color} />
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
          { key: "grid", header: "Grid", align: "right", render: (row) => gridLabel(row.grid) },
          { key: "laps", header: "Laps", align: "right", render: (row) => row.laps ?? "--" },
          {
            key: "gap",
            header: "Time / gap",
            align: "right",
            render: (row) => <Cell cell={resultTime(row)} mono />
          },
          { key: "status", header: "Status", render: (row) => row.status || "--" },
          { key: "points", header: "Pts", align: "right", render: (row) => pointsLabel(row.points) }
        ]}
      />
      <p className="text-xs text-slate-500">
        A gap is to the winner, for a car that finished on the winner&apos;s lap. A car that took the flag one or more
        laps behind is shown as laps down.
      </p>
    </div>
  );
}

/** A cell with whatever more is true of it on hover. */
function Cell({ cell, mono = false }: { cell: ResultCell; mono?: boolean }) {
  return (
    <span className={mono ? "font-mono" : undefined} title={cell.note ?? undefined}>
      {cell.text}
    </span>
  );
}
