"use client";

import Link from "next/link";

import { useNow } from "@/components/calendar/useNow";
import { usePublishedIndex } from "@/components/calendar/usePublishedIndex";
import { ChartPanel } from "@/components/charts/ChartPanel";
import { RacePaceChart } from "@/components/charts/RacePaceChart";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { MetricCard } from "@/components/dashboard/MetricCard";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { LoadFailure } from "@/components/published/LoadFailure";
import { RetryButton } from "@/components/published/RetryButton";
import { usePublishedArtifact } from "@/components/published/usePublishedArtifact";
import { usePublishedSession } from "@/components/published/usePublishedSession";
import { DriverBadge } from "@/components/session/Badges";
import { ArtifactSection } from "@/components/summary/ArtifactSection";
import { latestPublishedSession, nextSession, publishedSessions, seasonOverviews } from "@/lib/calendar";
import { teamColorByDriver } from "@/lib/driver-style";
import { sessionStart } from "@/lib/format";
import { readResults } from "@/lib/published/artifacts";
import type { SessionView } from "@/lib/published/client";
import { sessionHref } from "@/lib/published/lookup";
import type { ReadySession } from "@/lib/published/session";
import type { PublishedIndex } from "@/lib/published/types";
import { meetingHref, STANDINGS_PATH, STRATEGY_PATH, TELEMETRY_PATH } from "@/lib/routes";
import { readRacePace, readSessionFigures } from "@/lib/session-summaries";

const DESCRIPTION =
  "Explore every published session through race pace, telemetry, strategy, tyre, ideal-lap, and car-performance analysis.";

/**
 * The home page: what is published, and the most recent session at a glance.
 * Everything on it is read in the browser, so it is as current as the
 * publication and not as old as the last build of the site (AR-07).
 */
export function HomeDashboard() {
  const { state, retry } = usePublishedIndex();
  const latest = state.status === "ready" ? latestPublishedSession(state.index) : null;

  return (
    <div>
      <PageHeader
        eyebrow="Personal race intelligence"
        title="Your F1 analysis workspace"
        description={DESCRIPTION}
        actions={
          <>
            {latest ? (
              <Link
                className="rounded bg-redline px-4 py-2 text-sm font-bold text-white"
                href={sessionHref({ kind: "key", sessionKey: latest.key })}
              >
                Open latest session
              </Link>
            ) : null}
            <Link className="rounded border border-line px-4 py-2 text-sm font-bold text-slate-200" href={TELEMETRY_PATH}>
              Compare telemetry
            </Link>
          </>
        }
      />
      {state.status === "loading" ? <LoadingState label="Loading published data" /> : null}
      {/* Nothing below is drawn from a calendar that was not read, so an
          outage shows as an outage and never as a site with no sessions. */}
      {state.status === "failed" ? <LoadFailure failure={state.failure} onRetry={retry} /> : null}
      {state.status === "ready" ? (
        latest ? (
          <LatestSession index={state.index} sessionKey={latest.key} />
        ) : (
          <>
            <Overview index={state.index} view={null} />
            <NextUp index={state.index} />
            <div className="mt-5">
              <EmptyState
                title="No session is published yet"
                detail="The calendar was read, and none of its sessions has data yet. The latest session appears here without a new version of the site once one is published."
              />
            </div>
          </>
        )
      ) : null}
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <WorkspaceLink href={TELEMETRY_PATH} title="Compare telemetry" detail="Speed, inputs, time delta, and track trace" />
        <WorkspaceLink href={STRATEGY_PATH} title="Review strategy" detail="Stints, compounds, stops, and post-stop pace" />
        <WorkspaceLink href={STANDINGS_PATH} title="Season standings" detail="Drivers and constructors, as published after each round" />
      </div>
    </div>
  );
}

/**
 * The calendar's figures with the most recent published session under them.
 * The session is opened by its key through the loader every session page
 * uses, so what is shown of it comes from one generation (rule 1).
 */
function LatestSession({ index, sessionKey }: { index: PublishedIndex; sessionKey: number }) {
  const { state, retry } = usePublishedSession({ kind: "key", sessionKey });
  return (
    <>
      <Overview index={index} view={state.status === "ready" ? state.view : null} />
      <NextUp index={index} />
      <div className="mt-5">
        {state.status === "loading" ? <LoadingState label="Loading the latest session" /> : null}
        {state.status === "ready" ? <LatestPanels session={state} /> : null}
        {state.status === "failed" ? <LoadFailure failure={state.failure} onRetry={retry} /> : null}
        {state.status === "unpublished" || state.status === "unknown" ? (
          // The calendar names a latest session and its publication record is
          // not there: published a moment ago and not yet readable, or withdrawn.
          <div className="space-y-3">
            <EmptyState
              title="The latest session could not be opened"
              detail="The calendar lists it as published, and its publication record is not there. It may be a moment behind the calendar."
            />
            <div className="flex justify-center">
              <RetryButton onClick={retry} label="Check again" />
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}

/** The four figures at the top. Two come from the calendar and two from the latest session's files. */
function Overview({ index, view }: { index: PublishedIndex; view: SessionView | null }) {
  const published = publishedSessions(index);
  const seasons = seasonOverviews(index).length;
  const latest = published[0];
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        label="Published sessions"
        value={published.length}
        detail={`${seasons} ${seasons === 1 ? "season" : "seasons"} in the calendar`}
        tone="aqua"
      />
      <MetricCard
        label="Latest session"
        value={latest ? latest.name : "--"}
        detail={latest ? `${latest.meetingName}${latest.complete ? "" : " · partial data"}` : "Nothing is published yet"}
        tone="red"
      />
      {view ? (
        <SessionFigureCards view={view} />
      ) : (
        <>
          <MetricCard label="Session field" value="--" />
          <MetricCard label="Ideal-lap leader" value="--" tone="amber" />
        </>
      )}
    </div>
  );
}

function SessionFigureCards({ view }: { view: SessionView }) {
  const { artifact } = usePublishedArtifact(view, readSessionFigures);
  // These two cards are a glance, not the page: while their files load, or
  // if they cannot be read, the cards stay blank and say which it is.
  const pending = artifact.status === "loading" ? "Loading" : "Could not be loaded";
  const summary = artifact.status === "ready" ? artifact.data.summary : null;
  const leader = artifact.status === "ready" ? (artifact.data.idealLaps?.rows[0] ?? null) : null;
  const settled = artifact.status === "ready";
  return (
    <>
      <MetricCard
        label="Session field"
        value={summary ? summary.driver_count : "--"}
        detail={summary ? `${summary.lap_count} timing laps` : settled ? "Not published for this session" : pending}
      />
      <MetricCard
        label="Ideal-lap leader"
        value={leader ? leader.driver_code : "--"}
        detail={
          leader
            ? `${(Number(leader.delta_to_ideal_ms) / 1000).toFixed(3)}s left on track`
            : settled
              ? (summary?.weather_summary ?? "Not published for this session")
              : pending
        }
        tone="amber"
      />
    </>
  );
}

/** The next session of the calendar, which is the next thing that can be published. */
function NextUp({ index }: { index: PublishedIndex }) {
  const now = useNow();
  const next = nextSession(index, now);
  if (!next) {
    return null;
  }
  return (
    <p className="mt-4 text-sm text-slate-400">
      <span className="eyebrow mr-2">Next</span>
      <Link className="font-semibold text-slate-200 underline-offset-4 hover:underline" href={meetingHref(next.year, next.meeting.round)}>
        {next.meeting.name}
      </Link>{" "}
      · {next.session.name} · {sessionStart(next.session.start_time_utc)}
    </p>
  );
}

function LatestPanels({ session }: { session: ReadySession }) {
  const { view, heading } = session;
  const name = `${heading.meetingName} · ${heading.sessionName}`;
  const pace = usePublishedArtifact(view, readRacePace);
  const results = usePublishedArtifact(view, readResults);
  return (
    <div className="grid gap-5 xl:grid-cols-[1.3fr_0.7fr]">
      <ChartPanel title="Latest race pace" description={name}>
        <ArtifactSection name="race pace" artifact={pace.artifact} onRetry={pace.retry}>
          {(racePace) =>
            racePace && racePace.drivers.length > 0 ? (
              <RacePaceChart rows={racePace.drivers} />
            ) : (
              <p className="py-10 text-center text-sm text-slate-500">No race pace is published for this session.</p>
            )
          }
        </ArtifactSection>
      </ChartPanel>
      <ChartPanel title="Latest result" description={name}>
        <ArtifactSection name="results" artifact={results.artifact} onRetry={results.retry}>
          {({ results: rows, drivers }) => {
            const colors = teamColorByDriver(drivers);
            return rows.length === 0 ? (
              <p className="py-10 text-center text-sm text-slate-500">No classification was published for this session.</p>
            ) : (
              <div className="space-y-2">
                {rows.slice(0, 8).map((result) => (
                  <div
                    key={result.driver_code}
                    className="grid grid-cols-[28px_1fr_auto] items-center gap-3 rounded-md border border-line/60 bg-carbon/35 px-3 py-2.5"
                  >
                    <span className="font-mono text-xs text-slate-500">{result.position}</span>
                    <DriverBadge code={result.driver_code} color={colors[result.driver_code]} />
                    <span className="font-mono text-xs font-bold text-white">{result.points ?? 0} pts</span>
                  </div>
                ))}
              </div>
            );
          }}
        </ArtifactSection>
      </ChartPanel>
    </div>
  );
}

function WorkspaceLink({ href, title, detail }: { href: string; title: string; detail: string }) {
  return (
    <Link href={href} className="surface group p-4 transition hover:-translate-y-0.5 hover:border-redline/50">
      <div className="font-bold text-white transition group-hover:text-redline">{title} →</div>
      <div className="mt-1 text-sm text-slate-500">{detail}</div>
    </Link>
  );
}
