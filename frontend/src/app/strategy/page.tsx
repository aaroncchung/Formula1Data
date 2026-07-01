import { ChartPanel } from "@/components/charts/ChartPanel";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { PitStopTimeline } from "@/components/session/PitStopTimeline";
import { StintTimeline } from "@/components/session/StintTimeline";
import { api, isApiFailure, safeApi } from "@/lib/api-server";
import { DEFAULT_SESSION_ID } from "@/lib/constants";

export default async function StrategyPage() {
  const [stints, pitStops, strategy] = await Promise.all([
    safeApi(() => api.stints(DEFAULT_SESSION_ID)),
    safeApi(() => api.pitStops(DEFAULT_SESSION_ID)),
    safeApi(() => api.strategy(DEFAULT_SESSION_ID))
  ]);
  const failed = [stints, pitStops, strategy].find(isApiFailure);
  if (failed) {
    return <ErrorState title="Could not load strategy" detail={`${failed.error.message}: ${failed.apiBaseUrl}`} />;
  }
  if (!stints.ok || !pitStops.ok || !strategy.ok) {
    return null;
  }
  return (
    <div>
      <PageHeader title="Strategy" description="Stint structure, compound usage, pit stop timing, and basic undercut/overcut estimates." />
      <div className="space-y-5">
        <ChartPanel title="Stint Timeline">
          <StintTimeline stints={stints.data} />
        </ChartPanel>
        <ChartPanel title="Pit Stop Timing">
          <PitStopTimeline stops={pitStops.data} />
        </ChartPanel>
        <ChartPanel title="Strategy Payload">
          <pre className="max-h-[420px] overflow-auto text-xs text-slate-300">{JSON.stringify(strategy.data, null, 2)}</pre>
        </ChartPanel>
      </div>
    </div>
  );
}
