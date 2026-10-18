import { EmptyState } from "@/components/dashboard/EmptyState";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { drawFailureDetail, drawFailureTitle, failureDetail } from "@/components/published/failure-copy";
import { LoadFailure } from "@/components/published/LoadFailure";
import { RenderBoundary } from "@/components/published/RenderBoundary";
import { RetryButton } from "@/components/published/RetryButton";
import type { Artifact } from "@/components/published/usePublishedArtifact";

type ArtifactPanelProps<T> = {
  /**
   * The id of the tab this panel is the body of, which labels it. Left out on
   * a page that shows the read on its own, where there is no tab to name.
   */
  tab?: string;
  /** What the read shows, as it reads in a sentence: "results", "lap times". */
  name: string;
  artifact: Artifact<T>;
  onRetry: () => void;
  children: (data: T) => React.ReactNode;
};

/**
 * One read of a session's files in each state it can be in: the body of a
 * tab of the session dashboard, or of a page that summarises a session.
 * Whatever goes wrong here is shown here: the heading and the other reads on
 * the page do not depend on it (AR-07, where one failed artifact replaced the
 * whole page).
 */
export function ArtifactPanel<T>({ tab, name, artifact, onRetry, children }: ArtifactPanelProps<T>) {
  const body = (
    <>
      {/* A throw while drawing what was read is kept here too: it takes
          this panel, and not the tabs, the heading or the navigation around
          it. Trying again reads it again and draws it again. */}
      {artifact.status === "ready" ? (
        <RenderBoundary
          resetKey={artifact.data}
          fallback={(error, retry) => (
            <div className="space-y-3">
              <ErrorState title={drawFailureTitle(name)} detail={drawFailureDetail(error)} />
              <RetryButton
                onClick={() => {
                  retry();
                  onRetry();
                }}
              />
            </div>
          )}
        >
          <Drawn data={artifact.data} draw={children} />
        </RenderBoundary>
      ) : null}
      {artifact.status === "loading" ? <LoadingState label={`Loading ${name}`} /> : null}
      {artifact.status === "failed" ? <ArtifactFailure name={name} artifact={artifact} onRetry={onRetry} /> : null}
    </>
  );
  if (tab === undefined) {
    return body;
  }
  return (
    <div role="tabpanel" aria-labelledby={`session-tab-${tab}`}>
      {body}
    </div>
  );
}

/** What was read, drawn inside the boundary: called in the panel's own render, a throw would pass it by. */
function Drawn<T>({ data, draw }: { data: T; draw: (data: T) => React.ReactNode }) {
  return <>{draw(data)}</>;
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
  // now (usePublishedSession). This read is given the new view next, or the
  // page shows why there is none; either way this is not the read's error.
  if (failure.code === "generation_gone") {
    return <LoadingState label="This session was published again. Loading the new version." />;
  }
  // A generation does not have to hold every artifact: a practice session
  // has no classification, for instance. That is an absence, not a fault.
  if (failure.code === "not_in_manifest") {
    return <EmptyState title={`No ${name} for this session`} detail={failureDetail(failure)} />;
  }
  return <LoadFailure failure={failure} onRetry={onRetry} />;
}
