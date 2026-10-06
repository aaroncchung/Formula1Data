import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { CoverageShortfalls } from "@/components/published/Coverage";
import { LoadFailure } from "@/components/published/LoadFailure";
import { RetryButton } from "@/components/published/RetryButton";
import type { SessionState } from "@/components/published/usePublishedSession";
import type { SessionView } from "@/lib/published/client";
import type { SessionAddress, SessionHeading } from "@/lib/published/lookup";
import type { ReadySession, SessionLoad } from "@/lib/published/session";

type SessionStatesProps = {
  state: SessionState;
  /** How the page was asked for the session, which words "not found". */
  address: SessionAddress;
  onRetry: () => void;
  /**
   * What the page puts above the session in every state: its heading, and
   * whatever it shows about the session beside it. `heading` is null until
   * the session is known, and `view` until it is open.
   */
  above: (heading: SessionHeading | null, view: SessionView | null) => React.ReactNode;
  /** The page's content for a session that was opened. Everything it reads goes through `session.view`. */
  children: (session: ReadySession) => React.ReactNode;
};

/**
 * One session in each state its load can end in, for every page that shows
 * one: the session dashboard and the pages that summarise a session.
 *
 * Each state has its own rendering, because they call for different things
 * from the person looking: wait, pick another session, come back later, or
 * report a fault. They are worded here once, so "not published" reads the
 * same wherever a session is shown and is never drawn as a fault, and a
 * fault is never drawn as "not published".
 */
export function SessionStates({ state, address, onRetry, above, children }: SessionStatesProps) {
  if (state.status === "loading") {
    return (
      <div>
        {above(null, null)}
        <LoadingState label="Loading session" />
      </div>
    );
  }
  if (state.status === "unknown") {
    return (
      <div>
        {above(null, null)}
        <EmptyState title="Session not found" detail={unknownDetail(state.missing, address)} />
      </div>
    );
  }
  if (state.status === "unpublished") {
    return (
      <div>
        {above(state.heading, null)}
        <div className="space-y-3">
          <EmptyState
            title="Not published yet"
            detail="This session is in the calendar, and its data has not been published. It appears here without a new version of the site once it is."
          />
          <div className="flex justify-center">
            <RetryButton onClick={onRetry} label="Check again" />
          </div>
        </div>
      </div>
    );
  }
  if (state.status === "failed") {
    return (
      <div>
        {above(state.heading, null)}
        <LoadFailure failure={state.failure} onRetry={onRetry} />
      </div>
    );
  }
  return (
    <div>
      {above(state.heading, state.view)}
      {/* From the pointer of the generation on screen, not the calendar's copy of the verdict, which can lag. */}
      <CoverageShortfalls coverage={state.view.pointer.coverage} />
      {children(state)}
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
