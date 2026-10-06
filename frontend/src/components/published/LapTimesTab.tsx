"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { LapTimeChart } from "@/components/charts/LapTimeChart";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { ArtifactPanel } from "@/components/published/ArtifactPanel";
import { usePublishedArtifact } from "@/components/published/usePublishedArtifact";
import { readLapTimes } from "@/lib/published/artifacts";
import type { SessionView } from "@/lib/published/client";

export function LapTimesTab({ view, active }: { view: SessionView; active: boolean }) {
  const { artifact, retry } = usePublishedArtifact(view, readLapTimes);
  if (!active) {
    return null;
  }
  return (
    <ArtifactPanel tab="lap-times" name="lap times" artifact={artifact} onRetry={retry}>
      {({ series, drivers }) =>
        series.length === 0 ? (
          <EmptyState title="No lap times" detail="This session was published without any timed laps." />
        ) : (
          <ChartPanel title="Lap Time Evolution" description="All available lap times by driver.">
            <LapTimeChart series={series} drivers={drivers} />
          </ChartPanel>
        )
      }
    </ArtifactPanel>
  );
}
