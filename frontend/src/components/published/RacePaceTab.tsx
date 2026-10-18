"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { RacePaceChart } from "@/components/charts/RacePaceChart";
import { TyreDegradationChart } from "@/components/charts/TyreDegradationChart";
import { DataTable } from "@/components/data-table/DataTable";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { TyreFitTable } from "@/components/published/TyreFitTable";
import { DriverBadge } from "@/components/session/Badges";
import { teamColorByDriver } from "@/lib/driver-style";
import { formatDelta, formatMs } from "@/lib/format";
import { readRacePace, type SessionRacePace } from "@/lib/published/artifacts";

export function RacePaceTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="race-pace" name="race pace" read={readRacePace}>
      {(data) => <RacePace {...data} />}
    </SessionTab>
  );
}

function RacePace({ racePace, tyreDegradation, laps, drivers }: SessionRacePace) {
  const colors = teamColorByDriver(drivers);
  return (
    <div className="space-y-5">
      <ChartPanel title="Driver Race Pace" description={racePace.caveats.join(" ")}>
        <RacePaceChart rows={racePace.drivers} />
      </ChartPanel>
      <ChartPanel
        title="Tyre Degradation"
        description="Lap time against tyre age for every driver, with the fitted rate of each stint that has one."
      >
        <TyreDegradationChart laps={laps} degradation={tyreDegradation} drivers={drivers} />
      </ChartPanel>
      <DataTable
        rows={racePace.drivers}
        emptyText="No driver has a clean lap in this session."
        columns={[
          { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
          { key: "laps", header: "Clean laps", align: "right", render: (row) => row.lap_count },
          { key: "median", header: "Median", align: "right", render: (row) => formatMs(row.median_lap_ms) },
          { key: "trimmed", header: "Trimmed", align: "right", render: (row) => formatMs(row.trimmed_mean_lap_ms) },
          { key: "fastest", header: "Fastest", align: "right", render: (row) => formatMs(row.fastest_clean_lap_ms) },
          { key: "gap", header: "Gap", align: "right", render: (row) => formatDelta(row.gap_to_best_ms) }
        ]}
      />
      <TyreFitTable degradation={tyreDegradation} colors={colors} />
    </div>
  );
}
