import { ChartPanel } from "@/components/charts/ChartPanel";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { PitStopTimeline } from "@/components/session/PitStopTimeline";
import { StintTimeline } from "@/components/session/StintTimeline";
import { StrategyAnalysis } from "@/components/session/StrategyAnalysis";
import { api, isApiFailure, safeApi } from "@/lib/api-server";

export default async function StrategyPage() {
  const primarySession = await safeApi(() => api.primarySession());
  if (!primarySession.ok) {
    return <ErrorState title="Could not load strategy" detail={`${primarySession.error.message}: ${primarySession.apiBaseUrl}`} />;
  }
  const [stints, pitStops, strategy] = await Promise.all([
    safeApi(() => api.stints(primarySession.data.session_id)),
    safeApi(() => api.pitStops(primarySession.data.session_id)),
    safeApi(() => api.strategy(primarySession.data.session_id))
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
      <PageHeader title="Strategy" description="Stint structure, compound usage, pit-lane transit timing, and simple post-stop pace estimates." />
      <div className="space-y-5">
        <ChartPanel title="Stint Timeline">
          <StintTimeline stints={stints.data} />
        </ChartPanel>
        <ChartPanel title="Pit Stop Timing">
          <PitStopTimeline stops={pitStops.data} />
        </ChartPanel>
        <ChartPanel title="Strategy Analysis" description="Compound usage, stops, and simple post-stop pace estimates.">
          <StrategyAnalysis strategy={strategy.data} pitStops={pitStops.data} />
        </ChartPanel>
      </div>
    </div>
  );
}
