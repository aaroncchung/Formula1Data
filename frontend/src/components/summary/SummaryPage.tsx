"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { LoadFailure } from "@/components/calendar/LoadFailure";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { CoverageBadge, CoverageShortfalls } from "@/components/published/Coverage";
import { RetryButton } from "@/components/published/RetryButton";
import { SessionSelect } from "@/components/summary/SessionSelect";
import { useChosenSession } from "@/components/summary/useChosenSession";
import { describeSession } from "@/lib/chosen-session";
import type { ReadyChosenSession, SessionDescription } from "@/lib/chosen-session";
import { compactDate } from "@/lib/format";
import type { Coverage, PublishedIndex } from "@/lib/published/types";
import { sessionHref, sessionKeyParam, sessionSummaryHref } from "@/lib/routes";

type SummaryPageProps = {
  /** The page's own path, such as `/strategy`: choosing a session goes to it with that session's key. */
  path: string;
  title: string;
  description: string;
  /** The page's content for a session that was opened. Everything it reads goes through `session.view`. */
  children: (session: ReadyChosenSession) => React.ReactNode;
};

/**
 * A page that summarises one session: `/strategy`, `/telemetry`, `/drivers`,
 * `/teams`.
 *
 * These pages used to be built for whichever session was the most recent in
 * the repository on the day of the build. They now load in the browser, show
 * the most recent published session unless the address names one with
 * `?key=`, and let the reader choose another. The page is a static shell, so
 * a session published tomorrow needs no new build (AR-07).
 */
export function SummaryPage(props: SummaryPageProps) {
  const param = sessionKeyParam(useSearchParams());
  if (param.status === "invalid") {
    // A mistyped link is answered as one. Showing the latest session instead
    // would look like the answer to a question that was not asked.
    return (
      <div>
        <PageHeader title={props.title} description={props.description} />
        <EmptyState
          title="Not a session key"
          detail={`The address names the session "${param.raw}", and a session key is a number, as in ${sessionSummaryHref(props.path, 11315)}.`}
        />
        <div className="mt-4 text-center">
          <Link className="text-sm font-semibold text-slate-200 underline-offset-4 hover:underline" href={props.path}>
            Show the most recent session
          </Link>
        </div>
      </div>
    );
  }
  return <ChosenSummary {...props} requestedKey={param.status === "ok" ? param.value : null} />;
}

function ChosenSummary({
  path,
  title,
  description,
  requestedKey,
  children
}: SummaryPageProps & { requestedKey: number | null }) {
  const router = useRouter();
  const { state, retry } = useChosenSession(requestedKey);
  const choose = (sessionKey: number) => router.push(sessionSummaryHref(path, sessionKey));
  const header = <PageHeader title={title} description={description} />;

  if (state.status === "loading") {
    return (
      <div>
        {header}
        <LoadingState label="Loading session" />
      </div>
    );
  }
  if (state.status === "no_calendar") {
    return (
      <div>
        {header}
        <LoadFailure failure={state.failure} onRetry={retry} />
      </div>
    );
  }
  if (state.status === "none_published") {
    return (
      <div>
        {header}
        <EmptyState
          title="No session is published yet"
          detail="The calendar was read, and none of its sessions has data yet. This page fills in without a new version of the site once one is published."
        />
      </div>
    );
  }
  if (state.status === "unknown") {
    return (
      <div>
        {header}
        <SessionBar id={path} index={state.index} selectedKey={state.key} about={null} onChoose={choose} />
        <EmptyState
          title="Session not found"
          detail={`Nothing is published under the session key ${state.key}. Choose a session above.`}
        />
      </div>
    );
  }
  if (state.status === "unpublished") {
    return (
      <div>
        {header}
        <SessionBar
          id={path}
          index={state.index}
          selectedKey={state.key}
          about={describeSession(state.listing, null)}
          onChoose={choose}
        />
        <div className="space-y-3">
          <EmptyState
            title="Not published"
            detail="The calendar lists this session as published, and its publication record is not there. It may have been withdrawn, or the calendar may be a moment ahead of it."
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
        {header}
        <SessionBar
          id={path}
          index={state.index}
          selectedKey={state.key}
          about={describeSession(state.listing, null)}
          onChoose={choose}
        />
        <LoadFailure failure={state.failure} onRetry={retry} />
      </div>
    );
  }

  const { pointer } = state.view;
  return (
    <div>
      {header}
      <SessionBar
        id={path}
        index={state.index}
        selectedKey={state.key}
        about={describeSession(state.listing, pointer.identity)}
        coverage={pointer.coverage}
        dashboardKey={state.key}
        onChoose={choose}
      />
      <CoverageShortfalls coverage={pointer.coverage} />
      {children(state)}
      <p className="mt-6 text-xs text-slate-600">
        Published {compactDate(pointer.published_at)} · generation{" "}
        <span className="font-mono">{pointer.generation.slice(0, 12)}</span>
      </p>
    </div>
  );
}

type SessionBarProps = {
  /** Makes the control's id unique to the page. */
  id: string;
  index: PublishedIndex;
  selectedKey: number | null;
  /** Who the selected session is, when that is known. */
  about: SessionDescription | null;
  /** Given once the session is open: the verdict of the generation on screen, not the calendar's copy of it. */
  coverage?: Coverage;
  dashboardKey?: number;
  onChoose: (sessionKey: number) => void;
};

/** Which session the page is about, the control to change it, and the way to its full dashboard. */
function SessionBar({ id, index, selectedKey, about, coverage, dashboardKey, onChoose }: SessionBarProps) {
  const controlId = `session-select-${id.replaceAll("/", "")}`;
  const facts = about
    ? [
        about.round === null ? String(about.year) : `${about.year} Round ${about.round}`,
        compactDate(about.startTimeUtc),
        about.place
      ]
        .filter(Boolean)
        .join(" · ")
    : null;
  return (
    <section className="surface mb-5 flex flex-wrap items-center gap-x-4 gap-y-3 p-3" aria-label="Session">
      <label className="eyebrow shrink-0" htmlFor={controlId}>
        Session
      </label>
      <SessionSelect id={controlId} index={index} selectedKey={selectedKey} onChoose={onChoose} />
      {facts ? <div className="text-sm text-slate-400">{facts}</div> : null}
      <div className="ml-auto flex flex-wrap items-center gap-3">
        {coverage ? <CoverageBadge coverage={coverage} /> : null}
        {dashboardKey === undefined ? null : (
          <Link
            className="rounded border border-line px-3 py-1.5 text-xs font-bold text-slate-200 transition hover:border-redline/60"
            href={sessionHref(dashboardKey)}
          >
            Open session dashboard →
          </Link>
        )}
      </div>
    </section>
  );
}
