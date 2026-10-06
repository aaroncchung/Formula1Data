"use client";

import { ArtifactPanel } from "@/components/published/ArtifactPanel";
import { TelemetryLaps } from "@/components/published/TelemetryTab";
import { usePublishedArtifact } from "@/components/published/usePublishedArtifact";
import type { SessionView } from "@/lib/published/client";
import { readTelemetry } from "@/lib/published/telemetry";

/**
 * The telemetry page's content: the session dashboard's telemetry tab on a
 * page of its own, read by the tab's reader and drawn by the tab's body. It
 * opens on the fastest laps of the two quickest drivers, and every comparison
 * after that reads the two laps it compares from the same pinned generation.
 */
export function TelemetrySummary({ view }: { view: SessionView }) {
  const { artifact, retry } = usePublishedArtifact(view, readTelemetry);
  return (
    <ArtifactPanel name="telemetry" artifact={artifact} onRetry={retry}>
      {(telemetry) => <TelemetryLaps view={view} telemetry={telemetry} />}
    </ArtifactPanel>
  );
}
