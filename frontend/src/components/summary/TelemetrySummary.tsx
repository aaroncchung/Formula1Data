"use client";

import { useMemo } from "react";

import { EmptyState } from "@/components/dashboard/EmptyState";
import { usePublishedArtifact } from "@/components/published/usePublishedArtifact";
import { ArtifactSection } from "@/components/summary/ArtifactSection";
import { TelemetryComparePanel } from "@/components/telemetry/TelemetryComparePanel";
import type { SessionView } from "@/lib/published/client";
import { defaultTelemetryLaps, readTelemetryIndex } from "@/lib/session-summaries";
import type { TelemetryLap } from "@/lib/session-summaries";
import { telemetryComparerOf } from "@/lib/view-telemetry";

/**
 * The lap comparison for one session. Opening the page reads only the list of
 * laps that have telemetry. The two laps themselves, and the lap times shown
 * beside them, are read when the reader asks for a comparison, and from the
 * same pinned generation as the list.
 */
export function TelemetrySummary({ view }: { view: SessionView }) {
  const { artifact, retry } = usePublishedArtifact(view, readTelemetryIndex);
  return (
    <ArtifactSection name="telemetry" artifact={artifact} onRetry={retry}>
      {(index) =>
        index && index.laps.length > 0 ? (
          <TelemetryCompare view={view} laps={index.laps} />
        ) : (
          <EmptyState
            title="No telemetry for this session"
            detail={
              index
                ? "This session was published without any lap that has telemetry."
                : "No telemetry is published for this session."
            }
          />
        )
      }
    </ArtifactSection>
  );
}

function TelemetryCompare({ view, laps }: { view: SessionView; laps: TelemetryLap[] }) {
  const compare = useMemo(() => telemetryComparerOf(view), [view]);
  const start = defaultTelemetryLaps(laps);
  return (
    <TelemetryComparePanel
      // The panel keeps the reader's selection and the last comparison in its
      // own state. A new generation starts it afresh, so a comparison from
      // the old one is never shown as if it came from the new.
      key={view.pointer.generation}
      sessionId={String(view.pointer.session_key)}
      compare={compare}
      initialDriverA={start?.a.driver_code}
      initialLapA={start?.a.lap_number}
      initialDriverB={start?.b.driver_code}
      initialLapB={start?.b.lap_number}
      availableLaps={laps}
    />
  );
}
