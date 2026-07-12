import { ErrorState } from "@/components/dashboard/ErrorState";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { TelemetryComparePanel } from "@/components/telemetry/TelemetryComparePanel";
import { api, isEmptyState, safeApi } from "@/lib/api-server";

export default async function TelemetryPage() {
  const primarySession = await safeApi(() => api.primarySession());
  if (!primarySession.ok) {
    return <ErrorState title="Could not load telemetry" detail={`${primarySession.error.message}: ${primarySession.apiBaseUrl}`} />;
  }
  const telemetryIndex = await safeApi(() => api.telemetryIndex(primarySession.data.session_id));
  if (!telemetryIndex.ok) {
    return <ErrorState title="Could not load telemetry" detail={`${telemetryIndex.error.message}: ${telemetryIndex.apiBaseUrl}`} />;
  }
  if (!telemetryIndex.data?.laps.length) {
    return (
      <div>
        <PageHeader
          title="Telemetry"
          description="Compare any two drivers and laps. Static telemetry artifacts are aligned by distance and kept browser-sized."
        />
        <EmptyState
          title="Telemetry unavailable"
          detail="No telemetry lap artifacts are available for this session. Generate telemetry artifacts to enable driver and lap comparisons."
        />
      </div>
    );
  }
  const firstLap = telemetryIndex.data?.laps[0] || null;
  const secondLap =
    telemetryIndex.data?.laps.find((lap) => lap.driver_code !== firstLap?.driver_code) ||
    telemetryIndex.data?.laps[1] ||
    null;
  const comparison = firstLap && secondLap
    ? await safeApi(() =>
        api.telemetryCompare(
          primarySession.data.session_id,
          firstLap.driver_code,
          firstLap.lap_number,
          secondLap.driver_code,
          secondLap.lap_number
        )
      )
    : null;
  if (comparison && !comparison.ok) {
    return <ErrorState title="Could not load telemetry" detail={`${comparison.error.message}: ${comparison.apiBaseUrl}`} />;
  }
  return (
    <div>
      <PageHeader
        title="Telemetry"
        description="Compare any two drivers and laps. Static telemetry artifacts are aligned by distance and kept browser-sized."
      />
      <TelemetryComparePanel
        sessionId={primarySession.data.session_id}
        initialDriverA={firstLap?.driver_code}
        initialDriverB={secondLap?.driver_code}
        initialLapA={firstLap?.lap_number}
        initialLapB={secondLap?.lap_number}
        initialComparison={comparison && !isEmptyState(comparison.data) ? comparison.data : null}
        availableLaps={telemetryIndex.data.laps}
      />
    </div>
  );
}
