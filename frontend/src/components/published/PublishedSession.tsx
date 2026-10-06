"use client";

import { EmptyState } from "@/components/dashboard/EmptyState";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { CoverageBadge, CoverageShortfalls } from "@/components/published/Coverage";
import { failureDetail, failureTitle } from "@/components/published/failure-copy";
import { PublishedSessionTabs } from "@/components/published/PublishedSessionTabs";
import { RetryButton } from "@/components/published/RetryButton";
import { SessionHeader } from "@/components/published/SessionHeader";
import { usePublishedSession } from "@/components/published/usePublishedSession";
import { compactDate } from "@/lib/format";
import type { SessionView } from "@/lib/published/client";
import type { SessionRoute } from "@/lib/published/lookup";

/**
 * One session, loaded in the browser from published data.
 *
 * The page is a static shell: nothing about any session is known when the
 * site is built, so a session published tomorrow has a page today (AR-07).
 * Each state the load can end in has its own rendering, because they call for
 * different things from the person looking: wait, pick another session, come
 * back later, or report a fault.
 */
export function PublishedSession({ year, round, sessionType }: SessionRoute) {
  const { state, retry } = usePublishedSession(year, round, sessionType);

  if (state.status === "loading") {
    return <LoadingState label="Loading session" />;
  }
  if (state.status === "unknown") {
    return (
      <EmptyState
        title="Session not found"
        detail={unknownDetail(state.missing, { year, round, sessionType })}
      />
    );
  }
  if (state.status === "unpublished") {
    return (
      <div>
        <SessionHeader entry={state.entry} />
        <EmptyState
          title="Not published yet"
          detail="This session is in the calendar, and its data has not been published. It appears here without a new version of the site once it is."
          action={<RetryButton onClick={retry} label="Check again" />}
        />
      </div>
    );
  }
  if (state.status === "failed") {
    return (
      <div>
        {state.entry ? <SessionHeader entry={state.entry} /> : null}
        <div className="space-y-3">
          <ErrorState title={failureTitle(state.failure)} detail={failureDetail(state.failure)} />
          <RetryButton onClick={retry} />
        </div>
      </div>
    );
  }

  const { pointer } = state.view;
  return (
    <div>
      <SessionHeader entry={state.entry} actions={<CoverageBadge coverage={pointer.coverage} />} />
      <CoverageShortfalls coverage={pointer.coverage} />
      <PublishedSessionTabs view={state.view} />
      <GenerationNote view={state.view} />
    </div>
  );
}

function unknownDetail(missing: "year" | "round" | "session", route: SessionRoute): string {
  if (missing === "year") {
    return `There is no ${route.year} season in the published calendar.`;
  }
  if (missing === "round") {
    return `The ${route.year} calendar has no round ${route.round}.`;
  }
  return `Round ${route.round} of ${route.year} has no ${route.sessionType} session.`;
}

/** Which publication is on screen: everything above was read from this one generation. */
function GenerationNote({ view }: { view: SessionView }) {
  const { pointer, manifest } = view;
  return (
    <p className="mt-6 text-xs text-slate-600">
      Published {compactDate(pointer.published_at)} · generation{" "}
      <span className="font-mono">{pointer.generation.slice(0, 12)}</span> · {manifest.files.length} files
    </p>
  );
}
