"use client";

import Link from "next/link";

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
import { sessionHref } from "@/lib/published/lookup";
import type { SessionAddress } from "@/lib/published/lookup";
import type { SessionLoad } from "@/lib/published/session";

/**
 * One session, loaded in the browser from published data.
 *
 * The page is a static shell: nothing about any session is known when the
 * site is built, so a session published tomorrow has a page today (AR-07).
 * Each state the load can end in has its own rendering, because they call for
 * different things from the person looking: wait, pick another session, come
 * back later, or report a fault.
 */
export function PublishedSession({ address }: { address: SessionAddress }) {
  const { state, retry } = usePublishedSession(address);

  if (state.status === "loading") {
    return <LoadingState label="Loading session" />;
  }
  if (state.status === "unknown") {
    return <EmptyState title="Session not found" detail={unknownDetail(state.missing, address)} />;
  }
  if (state.status === "unpublished") {
    return (
      <div>
        <SessionHeader heading={state.heading} />
        <div className="space-y-3">
          <EmptyState
            title="Not published yet"
            detail="This session is in the calendar, and its data has not been published. It appears here without a new version of the site once it is."
          />
          <div className="flex justify-center">
            <RetryButton onClick={retry} label="Check again" />
          </div>
        </div>
      </div>
    );
  }
  if (state.status === "failed") {
    return (
      <div>
        {state.heading ? <SessionHeader heading={state.heading} /> : null}
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
      <SessionHeader heading={state.heading} actions={<CoverageBadge coverage={pointer.coverage} />} />
      <CoverageShortfalls coverage={pointer.coverage} />
      <PublishedSessionTabs view={state.view} />
      <GenerationNote view={state.view} byRound={address.kind === "route"} />
    </div>
  );
}

type Missing = Extract<SessionLoad, { status: "unknown" }>["missing"];

function unknownDetail(missing: Missing, address: SessionAddress): string {
  if (address.kind === "key") {
    return `No published session has the key ${address.sessionKey}.`;
  }
  const { route } = address;
  if (missing === "year") {
    return `There is no ${route.year} season in the published calendar.`;
  }
  if (missing === "round") {
    return `The ${route.year} calendar has no round ${route.round}.`;
  }
  return `Round ${route.round} of ${route.year} has no ${route.sessionType} session.`;
}

/**
 * Which publication is on screen: everything above was read from this one
 * generation. A page reached by year and round also offers its address by
 * key, which is the one to keep: a round names another race once the calendar
 * moves (AR-20).
 */
function GenerationNote({ view, byRound }: { view: SessionView; byRound: boolean }) {
  const { pointer, manifest } = view;
  return (
    <p className="mt-6 text-xs text-slate-600">
      Published {compactDate(pointer.published_at)} · generation{" "}
      <span className="font-mono">{pointer.generation.slice(0, 12)}</span> · {manifest.files.length} files · session key{" "}
      <span className="font-mono">{pointer.session_key}</span>
      {byRound ? (
        <>
          {" · "}
          <Link
            className="text-slate-400 underline decoration-slate-600 underline-offset-2 hover:text-white"
            href={sessionHref({ kind: "key", sessionKey: pointer.session_key })}
          >
            Permanent link
          </Link>
        </>
      ) : null}
    </p>
  );
}
