import { EmptyState } from "@/components/dashboard/EmptyState";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { failureDetail, failureTitle } from "@/components/published/failure-copy";
import { RetryButton } from "@/components/published/RetryButton";
import type { Artifact } from "@/components/published/usePublishedArtifact";

type ArtifactPanelProps<T> = {
  /** The id of the tab this panel belongs to, which labels it. */
  tab: string;
  /** What the tab shows, as it reads in a sentence: "results", "lap times". */
  name: string;
  artifact: Artifact<T>;
  onRetry: () => void;
  children: (data: T) => React.ReactNode;
};

/**
 * The body of one tab in each state its own read can be in. Whatever goes
 * wrong here is shown here: the header and the other tabs do not depend on
 * it (AR-07, where one failed artifact replaced the whole page).
 */
export function ArtifactPanel<T>({ tab, name, artifact, onRetry, children }: ArtifactPanelProps<T>) {
  return (
    <div role="tabpanel" aria-labelledby={`session-tab-${tab}`}>
      {artifact.status === "ready" ? children(artifact.data) : null}
      {artifact.status === "loading" ? <LoadingState label={`Loading ${name}`} /> : null}
      {artifact.status === "failed" ? <ArtifactFailure name={name} artifact={artifact} onRetry={onRetry} /> : null}
    </div>
  );
}

function ArtifactFailure<T>({
  name,
  artifact,
  onRetry
}: {
  name: string;
  artifact: Extract<Artifact<T>, { status: "failed" }>;
  onRetry: () => void;
}) {
  const { failure } = artifact;
  // The session is being opened again on the generation the pointer names
  // now (usePublishedSession). This tab is given the new view next, or the
  // page shows why there is none; either way this is not the tab's error.
  if (failure.code === "generation_gone") {
    return <LoadingState label="This session was published again. Loading the new version." />;
  }
  // A generation does not have to hold every artifact: a practice session
  // has no classification, for instance. That is an absence, not a fault.
  if (failure.code === "not_in_manifest") {
    return <EmptyState title={`No ${name} for this session`} detail={failureDetail(failure)} />;
  }
  return (
    <div className="space-y-3">
      <ErrorState title={failureTitle(failure)} detail={failureDetail(failure)} />
      <RetryButton onClick={onRetry} />
    </div>
  );
}
