"use client";

import { useCallback } from "react";

import { EmptyState } from "@/components/dashboard/EmptyState";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { TelemetryComparePanel } from "@/components/telemetry/TelemetryComparePanel";
import { api, isEmptyState } from "@/lib/api";
import { useRuntimeData } from "@/lib/use-runtime-data";

export default function TelemetryPage() {
  const load = useCallback(async () => {
    const session = await api.primarySession();
    const telemetryIndex = await api.telemetryIndex(session.session_id);
    const firstLap = telemetryIndex?.laps[0] || null;
    const secondLap = telemetryIndex?.laps.find((lap) => lap.driver_code !== firstLap?.driver_code) || telemetryIndex?.laps[1] || null;
    const comparison = firstLap && secondLap
      ? await api.telemetryCompare(session.session_id, firstLap.driver_code, firstLap.lap_number, secondLap.driver_code, secondLap.lap_number)
      : null;
    return { session, telemetryIndex, firstLap, secondLap, comparison };
  }, []);
  const state = useRuntimeData(load);
  if (state.state === "loading") return <LoadingState label="Loading current telemetry artifacts" />;
  if (state.state === "error") return <ErrorState title="Could not load telemetry" detail={state.detail} />;
  const { session, telemetryIndex, firstLap, secondLap, comparison } = state.data;
  if (!telemetryIndex?.laps.length) {
    return <div><PageHeader title="Telemetry" description="Compare any two drivers and laps. Published telemetry artifacts are aligned by distance and kept browser-sized." /><EmptyState title="Telemetry unavailable" detail="No telemetry lap artifacts are available for this session. Generate telemetry artifacts to enable driver and lap comparisons." /></div>;
  }
  return <div><PageHeader title="Telemetry" description="Compare any two drivers and laps. Published telemetry artifacts are aligned by distance and kept browser-sized." /><TelemetryComparePanel sessionId={session.session_id} initialDriverA={firstLap?.driver_code} initialDriverB={secondLap?.driver_code} initialLapA={firstLap?.lap_number} initialLapB={secondLap?.lap_number} initialComparison={comparison && !isEmptyState(comparison) ? comparison : null} availableLaps={telemetryIndex.laps} /></div>;
}
