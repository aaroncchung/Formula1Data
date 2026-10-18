"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { LapTimeChart } from "@/components/charts/LapTimeChart";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { readLapTimes } from "@/lib/published/artifacts";

export function LapTimesTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="lap-times" name="lap times" read={readLapTimes}>
      {({ series, drivers }) =>
        series.length === 0 ? (
          <EmptyState title="No lap times" detail="This session was published without any timed laps." />
        ) : (
          <ChartPanel title="Lap Time Evolution" description="All available lap times by driver.">
            <LapTimeChart series={series} drivers={drivers} />
          </ChartPanel>
        )
      }
    </SessionTab>
  );
}
