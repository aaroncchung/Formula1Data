"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { usePublishedIndex } from "@/components/calendar/usePublishedIndex";
import type { IndexState } from "@/components/calendar/usePublishedIndex";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { CoverageBadge } from "@/components/published/Coverage";
import { GenerationNote } from "@/components/published/GenerationNote";
import { LoadFailure } from "@/components/published/LoadFailure";
import { SessionStates } from "@/components/published/SessionStates";
import { usePublishedSession } from "@/components/published/usePublishedSession";
import { SessionSelect } from "@/components/summary/SessionSelect";
import { latestPublishedSession } from "@/lib/calendar";
import { compactDate } from "@/lib/format";
import type { SessionView } from "@/lib/published/client";
import { sessionHref } from "@/lib/published/lookup";
import type { SessionAddress, SessionHeading } from "@/lib/published/lookup";
import type { ReadySession } from "@/lib/published/session";
import { sessionChoice, sessionSummaryHref } from "@/lib/routes";

type SummaryPageProps = {
  /** The page's own path, such as `/strategy`: choosing a session goes to it with that session's key. */
  path: string;
  title: string;
  description: string;
  /** The page's content for a session that was opened. Everything it reads goes through `session.view`. */
  children: (session: ReadySession) => React.ReactNode;
};

/**
 * A page that summarises one session: `/strategy`, `/telemetry`, `/drivers`,
 * `/teams`.
 *
 * These pages used to be built for whichever session was the most recent in
 * the repository on the day of the build. They now load in the browser, show
 * the session their address names, as `/session` does, or the most recent
 * published one when it names none, and let the reader choose another. The
 * page is a static shell, so a session published tomorrow needs no new build
 * (AR-07).
 *
 * The session is opened by the loader the session dashboard uses
 * (`usePublishedSession`), so there is one way a page comes to hold a session
 * and everything it then reads comes from one generation (rule 1).
 */
export function SummaryPage(props: SummaryPageProps) {
  const choice = sessionChoice(useSearchParams());
  // The calendar, for the list of sessions to choose from and for knowing
  // which is the most recent. A session named in the address is opened
  // whether or not it could be read.
  const calendar = usePublishedIndex();
  const header = <PageHeader title={props.title} description={props.description} />;

  if (choice.kind === "invalid") {
    // A mistyped link is answered as one. Showing the latest session instead
    // would look like the answer to a question that was not asked.
    return (
      <div>
        {header}
        <EmptyState
          title="Not a session"
          detail={`The address does not name a session. A session is named by its key, as in ${sessionSummaryHref(props.path, 11315)}.`}
        />
        <div className="mt-4 text-center">
          <Link className="text-sm font-semibold text-slate-200 underline-offset-4 hover:underline" href={props.path}>
            Show the most recent session
          </Link>
        </div>
      </div>
    );
  }
  if (choice.kind === "named") {
    return <SessionSummary {...props} address={choice.address} calendar={calendar.state} onRetryCalendar={calendar.retry} />;
  }

  // No session is named, so which one to show is the calendar's to say.
  if (calendar.state.status === "loading") {
    return (
      <div>
        {header}
        <LoadingState label="Loading the calendar" />
      </div>
    );
  }
  if (calendar.state.status === "failed") {
    return (
      <div>
        {header}
        <LoadFailure failure={calendar.state.failure} onRetry={calendar.retry} />
      </div>
    );
  }
  const latest = latestPublishedSession(calendar.state.index);
  if (!latest) {
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
  return (
    <SessionSummary
      {...props}
      address={{ kind: "key", sessionKey: latest.key }}
      calendar={calendar.state}
      onRetryCalendar={calendar.retry}
    />
  );
}

type SessionSummaryProps = SummaryPageProps & {
  address: SessionAddress;
  calendar: IndexState;
  onRetryCalendar: () => void;
};

function SessionSummary({ path, title, description, address, calendar, onRetryCalendar, children }: SessionSummaryProps) {
  const router = useRouter();
  const { state, retry } = usePublishedSession(address);
  return (
    <SessionStates
      state={state}
      address={address}
      onRetry={retry}
      above={(heading, view) => (
        <>
          <PageHeader title={title} description={description} />
          <SessionBar
            id={path}
            calendar={calendar}
            onRetryCalendar={onRetryCalendar}
            selectedKey={view?.pointer.session_key ?? (address.kind === "key" ? address.sessionKey : null)}
            heading={heading}
            view={view}
            onChoose={(sessionKey) => router.push(sessionSummaryHref(path, sessionKey))}
          />
        </>
      )}
    >
      {(session) => (
        <>
          {children(session)}
          <GenerationNote
            view={session.view}
            // Reached by year and round: the same page by key is the address to keep.
            permanentHref={address.kind === "route" ? sessionSummaryHref(path, session.view.pointer.session_key) : null}
          />
        </>
      )}
    </SessionStates>
  );
}

type SessionBarProps = {
  /** Makes the control's id unique to the page. */
  id: string;
  calendar: IndexState;
  onRetryCalendar: () => void;
  /** The session on the page, when its key is known. */
  selectedKey: number | null;
  /** Who the session is, once the calendar or its pointer has said. */
  heading: SessionHeading | null;
  /** The open session: its coverage is the verdict of the generation on screen. */
  view: SessionView | null;
  onChoose: (sessionKey: number) => void;
};

/** Which session the page is about, the control to change it, and the way to its full dashboard. */
function SessionBar({ id, calendar, onRetryCalendar, selectedKey, heading, view, onChoose }: SessionBarProps) {
  const controlId = `session-select-${id.replaceAll("/", "")}`;
  const facts = heading
    ? [
        heading.round === null ? String(heading.year) : `${heading.year} Round ${heading.round}`,
        compactDate(heading.startTimeUtc),
        [heading.location, heading.country].filter(Boolean).join(", ")
      ]
        .filter(Boolean)
        .join(" · ")
    : null;
  return (
    <section className="surface mb-5 flex flex-wrap items-center gap-x-4 gap-y-3 p-3" aria-label="Session">
      <label className="eyebrow shrink-0" htmlFor={controlId}>
        Session
      </label>
      {calendar.status === "ready" ? (
        <SessionSelect id={controlId} index={calendar.index} selectedKey={selectedKey} onChoose={onChoose} />
      ) : (
        // The session on the page was opened from its own pointer, so it is
        // shown even when the list of the others is not there to choose from.
        <select id={controlId} className="control h-9 min-w-0 max-w-full flex-1 sm:max-w-[26rem]" disabled>
          <option>{calendar.status === "loading" ? "Loading sessions" : "Sessions unavailable"}</option>
        </select>
      )}
      {calendar.status === "failed" ? (
        <button
          type="button"
          className="text-xs font-semibold text-slate-300 underline underline-offset-2 hover:text-white"
          onClick={onRetryCalendar}
          title={calendar.failure.message}
        >
          The list of sessions could not be loaded. Try again
        </button>
      ) : null}
      {facts ? <div className="text-sm text-slate-400">{facts}</div> : null}
      <div className="ml-auto flex flex-wrap items-center gap-3">
        {view ? <CoverageBadge coverage={view.pointer.coverage} /> : null}
        {view ? (
          <Link
            className="rounded border border-line px-3 py-1.5 text-xs font-bold text-slate-200 transition hover:border-redline/60"
            href={sessionHref({ kind: "key", sessionKey: view.pointer.session_key })}
          >
            Open session dashboard →
          </Link>
        ) : null}
      </div>
    </section>
  );
}
