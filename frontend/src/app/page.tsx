import Link from "next/link";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { RacePaceChart } from "@/components/charts/RacePaceChart";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { MetricCard } from "@/components/dashboard/MetricCard";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { api, isApiFailure, safeApi } from "@/lib/api-server";

export default async function DashboardPage() {
  const primarySessionResult = await safeApi(() => api.primarySession());
  if (!primarySessionResult.ok) {
    return (
      <ErrorState
        title="Static data unavailable"
        detail={`${primarySessionResult.error.message}. Static data source: ${primarySessionResult.apiBaseUrl}`}
      />
    );
  }
  const primarySession = primarySessionResult.data;
  const [summaryResult, seasonsResult, racePaceResult] = await Promise.all([
    safeApi(() => api.summary(primarySession.session_id)),
    safeApi(() => api.seasons()),
    safeApi(() => api.racePace(primarySession.session_id))
  ]);

  const failed = [summaryResult, seasonsResult, racePaceResult].find(isApiFailure);
  if (failed) {
    return (
      <ErrorState
        title="Static data unavailable"
        detail={`${failed.error.message}. Static data source: ${failed.apiBaseUrl}`}
      />
    );
  }
  if (!summaryResult.ok || !seasonsResult.ok || !racePaceResult.ok) {
    return null;
  }

  const summary = summaryResult.data;
  const seasons = seasonsResult.data;
  const racePace = racePaceResult.data;

  return (
    <div>
      <PageHeader
        eyebrow="Personal motorsport analytics"
        title="Formula 1 Data"
        description="A dense, dark analytics workspace for historical race analysis, telemetry comparison, strategy review, and optional future live data."
        actions={
          <>
            <Link
              className="rounded bg-redline px-4 py-2 text-sm font-bold text-white"
              href={`/seasons/${primarySession.year}/${primarySession.round}/${primarySession.type}`}
            >
              Open latest session
            </Link>
            <Link className="rounded border border-line px-4 py-2 text-sm font-bold text-slate-200" href="/telemetry">
              Compare telemetry
            </Link>
          </>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Available seasons" value={seasons.length} detail="from processed artifacts" tone="aqua" />
        <MetricCard label="Latest session" value={summary.session} detail={summary.meeting} tone="red" />
        <MetricCard label="Drivers" value={summary.driver_count} detail={summary.circuit} />
        <MetricCard label="Mode" value={summary.is_sample ? "Demo" : "Historical"} detail={summary.weather_summary} tone="amber" />
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-[1.3fr_0.7fr]">
        <ChartPanel title="Latest Race Pace">
          <RacePaceChart rows={racePace.drivers} />
        </ChartPanel>
        <section className="rounded border border-line bg-panel p-4 shadow-panel">
          <h2 className="font-bold text-white">Data readiness</h2>
          <div className="mt-4 space-y-3 text-sm text-slate-300">
            <div className="flex justify-between gap-3 border-b border-line pb-2">
              <span>Sample artifacts</span>
              <span className="font-bold text-aqua">Ready</span>
            </div>
            <div className="flex justify-between gap-3 border-b border-line pb-2">
              <span>Pipeline ingest path</span>
              <span className="font-bold text-aqua">Implemented</span>
            </div>
            <div className="flex justify-between gap-3 border-b border-line pb-2">
              <span>OpenF1 live mode</span>
              <span className="font-bold text-amber">Future optional</span>
            </div>
            <div className="flex justify-between gap-3">
              <span>Frontend data</span>
              <span className="font-bold text-aqua">Static JSON</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
