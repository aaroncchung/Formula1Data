"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { usePublishedArtifact } from "@/components/published/usePublishedArtifact";
import { PitStopTimeline } from "@/components/session/PitStopTimeline";
import { StintTimeline } from "@/components/session/StintTimeline";
import { StrategyAnalysis } from "@/components/session/StrategyAnalysis";
import { ArtifactSection } from "@/components/summary/ArtifactSection";
import type { SessionView } from "@/lib/published/client";
import { readStrategy } from "@/lib/session-summaries";

export function StrategySummary({ view }: { view: SessionView }) {
  const { artifact, retry } = usePublishedArtifact(view, readStrategy);
  return (
    <ArtifactSection name="strategy" artifact={artifact} onRetry={retry}>
      {({ stints, pitStops, strategy }) => (
        <div className="space-y-5">
          <ChartPanel title="Stint Timeline">
            {stints && stints.length > 0 ? (
              <StintTimeline stints={stints} />
            ) : (
              <Absent>{stints ? "This session was published without any stints." : "No stints are published for this session."}</Absent>
            )}
          </ChartPanel>
          <ChartPanel title="Pit Stop Timing">
            {pitStops ? <PitStopTimeline stops={pitStops} /> : <Absent>No pit stops are published for this session.</Absent>}
          </ChartPanel>
          <ChartPanel title="Strategy Analysis" description="Compound usage, stops, and simple post-stop pace estimates.">
            {strategy || pitStops ? (
              <StrategyAnalysis strategy={strategy} pitStops={pitStops ?? []} />
            ) : (
              <Absent>No strategy analysis is published for this session.</Absent>
            )}
          </ChartPanel>
        </div>
      )}
    </ArtifactSection>
  );
}

/** A panel whose file the generation does not hold, or holds empty. An absence, not a fault. */
function Absent({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-dashed border-line p-6 text-center text-sm text-slate-500">{children}</div>;
}
