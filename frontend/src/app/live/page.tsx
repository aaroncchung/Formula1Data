import { ChartPanel } from "@/components/charts/ChartPanel";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { LiveTimingBoard } from "@/components/live/LiveTimingBoard";
import { api, isApiFailure, safeApi } from "@/lib/api-server";

export default async function LivePage() {
  const [current, timing, raceControl, positions, weather] = await Promise.all([
    safeApi(() => api.liveCurrentSession()),
    safeApi(() => api.liveTiming()),
    safeApi(() => api.liveRaceControl()),
    safeApi(() => api.livePositions()),
    safeApi(() => api.liveWeather())
  ]);
  const failed = [current, timing, raceControl, positions, weather].find(isApiFailure);
  if (failed) {
    return <ErrorState title="Could not load live data" detail={`${failed.error.message}: ${failed.apiBaseUrl}`} />;
  }
  if (!current.ok || !timing.ok || !raceControl.ok || !positions.ok || !weather.ok) {
    return null;
  }
  return (
    <div>
      <PageHeader title="Live" description="Optional future OpenF1 live timing. Static historical browsing does not require this path." />
      <div className="grid gap-5 xl:grid-cols-2">
        <ChartPanel title="Current Session">
          <LiveTimingBoard payload={current.data} />
        </ChartPanel>
        <ChartPanel title="Timing">
          <LiveTimingBoard payload={timing.data} />
        </ChartPanel>
        <ChartPanel title="Race Control">
          <LiveTimingBoard payload={raceControl.data} />
        </ChartPanel>
        <ChartPanel title="Positions">
          <LiveTimingBoard payload={positions.data} />
        </ChartPanel>
        <ChartPanel title="Weather">
          <LiveTimingBoard payload={weather.data} />
        </ChartPanel>
      </div>
    </div>
  );
}
