import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { TelemetryComparePanel } from "@/components/telemetry/TelemetryComparePanel";
import { api, isEmptyState, safeApi } from "@/lib/api-server";
import { DEFAULT_SESSION_ID } from "@/lib/constants";

export default async function TelemetryPage() {
  const comparison = await safeApi(() => api.telemetryCompare(DEFAULT_SESSION_ID, "VER", 6, "LEC", 7));
  if (!comparison.ok) {
    return <ErrorState title="Could not load telemetry" detail={`${comparison.error.message}: ${comparison.apiBaseUrl}`} />;
  }
  return (
    <div>
      <PageHeader
        title="Telemetry"
        description="Compare any two drivers and laps. Static telemetry artifacts are aligned by distance and kept browser-sized."
      />
      <TelemetryComparePanel
        sessionId={DEFAULT_SESSION_ID}
        initialComparison={isEmptyState(comparison.data) ? null : comparison.data}
      />
    </div>
  );
}
