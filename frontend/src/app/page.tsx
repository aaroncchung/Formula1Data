"use client";

import Link from "next/link";
import { useCallback } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { RacePaceChart } from "@/components/charts/RacePaceChart";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { MetricCard } from "@/components/dashboard/MetricCard";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge } from "@/components/session/Badges";
import { api } from "@/lib/api";
import { sessionHref } from "@/lib/season-routes";
import { useRuntimeData } from "@/lib/use-runtime-data";

export default function DashboardPage() {
  const load = useCallback(async () => {
    const primarySession = await api.primarySession();
    const [summary, catalog, racePace, results, drivers, idealLaps] = await Promise.all([
      api.summary(primarySession.session_id),
      api.catalog(),
      api.racePace(primarySession.session_id),
      api.results(primarySession.session_id).catch(() => []),
      api.drivers(primarySession.session_id).catch(() => []),
      api.idealLaps(primarySession.session_id).catch(() => null)
    ]);
    return { primarySession, summary, catalog, racePace, results, drivers, idealLaps };
  }, []);
  const state = useRuntimeData(load);

  if (state.state === "loading") return <LoadingState label="Loading current R2 catalog" />;
  if (state.state === "error") return <ErrorState title="Artifact data unavailable" detail={state.detail} />;

  const { primarySession, summary, catalog, racePace, results, drivers, idealLaps } = state.data;
  const colors = Object.fromEntries(drivers.map((driver) => [driver.code, driver.team.color]));
  const bestIdeal = idealLaps?.rows[0] || null;

  return (
    <div>
      <PageHeader
        eyebrow="Personal race intelligence"
        title="Your F1 analysis workspace"
        description="Explore every processed session through race pace, telemetry, strategy, tyre, ideal-lap, and car-performance analysis—without a paid backend."
        actions={
          <>
            <Link className="rounded bg-redline px-4 py-2 text-sm font-bold text-white" href={sessionHref(primarySession.year, primarySession.round, primarySession.type)}>
              Open latest session
            </Link>
            <Link className="rounded border border-line px-4 py-2 text-sm font-bold text-slate-200" href="/telemetry">
              Compare telemetry
            </Link>
          </>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Available seasons" value={catalog.seasons.length} detail={`${catalog.sessions.filter((session) => session.status !== "missing").length} sessions ready`} tone="aqua" />
        <MetricCard label="Latest session" value={summary.session} detail={summary.meeting} tone="red" />
        <MetricCard label="Session field" value={summary.driver_count} detail={`${summary.lap_count} timing laps`} />
        <MetricCard label="Ideal-lap leader" value={bestIdeal?.driver_code || "--"} detail={bestIdeal ? `${(Number(bestIdeal.delta_to_ideal_ms) / 1000).toFixed(3)}s left on track` : summary.weather_summary} tone="amber" />
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-[1.3fr_0.7fr]">
        <ChartPanel title="Latest Race Pace"><RacePaceChart rows={racePace.drivers} /></ChartPanel>
        <ChartPanel title="Latest result" description={`${summary.meeting} · ${summary.session}`}>
          <div className="space-y-2">
            {results.slice(0, 8).map((result) => (
              <div key={result.driver_code} className="grid grid-cols-[28px_1fr_auto] items-center gap-3 rounded-md border border-line/60 bg-carbon/35 px-3 py-2.5">
                <span className="font-mono text-xs text-slate-500">{result.position}</span>
                <DriverBadge code={result.driver_code} color={colors[result.driver_code]} />
                <span className="font-mono text-xs font-bold text-white">{result.points || 0} pts</span>
              </div>
            ))}
          </div>
        </ChartPanel>
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <WorkspaceLink href="/telemetry" title="Compare telemetry" detail="Speed, inputs, time delta, and track trace" />
        <WorkspaceLink href="/strategy" title="Review strategy" detail="Stints, compounds, stops, and post-stop pace" />
        <WorkspaceLink href="/standings" title="Season standings" detail="Drivers and constructors from available results" />
      </div>
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
