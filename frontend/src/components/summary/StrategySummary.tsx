"use client";

import { ArtifactPanel } from "@/components/published/ArtifactPanel";
import { StrategyPanels } from "@/components/published/StrategyTab";
import { usePublishedArtifact } from "@/components/published/usePublishedArtifact";
import { readStrategy } from "@/lib/published/artifacts";
import type { SessionView } from "@/lib/published/client";

/**
 * The strategy page's content: the session dashboard's strategy tab on a page
 * of its own, read by the tab's reader and drawn by the tab's body, so the two
 * cannot show a session's strategy differently.
 */
export function StrategySummary({ view }: { view: SessionView }) {
  const { artifact, retry } = usePublishedArtifact(view, readStrategy);
  return (
    <ArtifactPanel name="strategy" artifact={artifact} onRetry={retry}>
      {(strategy) => <StrategyPanels {...strategy} />}
    </ArtifactPanel>
  );
}
