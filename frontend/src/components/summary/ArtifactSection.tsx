import { LoadFailure } from "@/components/calendar/LoadFailure";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { failureDetail } from "@/components/published/failure-copy";
import type { Artifact } from "@/components/published/usePublishedArtifact";

type ArtifactSectionProps<T> = {
  /** What the section shows, as it reads in a sentence: "strategy", "drivers". */
  name: string;
  artifact: Artifact<T>;
  onRetry: () => void;
  children: (data: T) => React.ReactNode;
};

/**
 * One part of a summary page in each state its own read can be in. It is
 * `ArtifactPanel` without the tab: whatever goes wrong with this read is
 * shown here, and the heading, the session bar and the other sections do not
 * depend on it (AR-07, where one failed artifact replaced the whole page).
 */
export function ArtifactSection<T>({ name, artifact, onRetry, children }: ArtifactSectionProps<T>) {
  if (artifact.status === "ready") {
    return <>{children(artifact.data)}</>;
  }
  if (artifact.status === "loading") {
    return <LoadingState label={`Loading ${name}`} />;
  }
  const { failure } = artifact;
  // The session is being opened again on the generation its pointer names now
  // (useChosenSession). This section is given the new view next, or the page
  // shows why there is none.
  if (failure.code === "generation_gone") {
    return <LoadingState label="This session was published again. Loading the new version." />;
  }
  if (failure.code === "not_in_manifest") {
    return <EmptyState title={`No ${name} for this session`} detail={failureDetail(failure)} />;
  }
  return <LoadFailure failure={failure} onRetry={onRetry} />;
}
