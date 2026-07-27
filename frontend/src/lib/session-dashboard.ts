import type { SessionTabsProps } from "@/components/session/SessionTabs";
import { safeApi, type ApiFailure, type StaticApi, type TelemetryIndex } from "@/lib/static-api-core";
import type { ApiResult } from "@/types/api";
import type { EmptyStateResponse, TelemetryComparison } from "@/types/domain";

export type SessionDashboardLoad =
  | { ok: true; data: SessionTabsProps }
  | { ok: false; stage: "artifacts" | "telemetry"; failure: ApiFailure };

/**
 * Loads every artifact `SessionTabs` renders and returns a complete
 * `SessionTabsProps`. Both the statically rendered session page and the
 * on-demand ingestion panel go through here so the two cannot diverge.
 */
export async function loadSessionDashboard(api: StaticApi, sessionId: string): Promise<SessionDashboardLoad> {
  const [
    summary,
    drivers,
    laps,
    lapTimes,
    racePace,
    tyreDegradation,
    stints,
    pitStops,
    weather,
    raceControl,
    results,
    telemetryIndex,
    positionReplay,
    idealLaps,
    teammateComparison,
    strategy,
    trackDominance,
    cornerAnalysis,
    carPerformance,
    pacePrediction
  ] = await Promise.all([
    safeApi(() => api.summary(sessionId)),
    safeApi(() => api.drivers(sessionId)),
    safeApi(() => api.laps(sessionId)),
    safeApi(() => api.lapTimes(sessionId)),
    safeApi(() => api.racePace(sessionId)),
    safeApi(() => api.tyreDegradation(sessionId)),
    safeApi(() => api.stints(sessionId)),
    safeApi(() => api.pitStops(sessionId)),
    safeApi(() => api.weather(sessionId)),
    safeApi(() => api.raceControl(sessionId)),
    safeApi(() => api.results(sessionId)),
    safeApi(() => api.telemetryIndex(sessionId)),
    safeApi(() => api.positionReplay(sessionId)),
    safeApi(() => api.idealLaps(sessionId)),
    safeApi(() => api.teammateComparison(sessionId)),
    safeApi(() => api.strategy(sessionId)),
    safeApi(() => api.trackDominance(sessionId)),
    safeApi(() => api.cornerAnalysis(sessionId)),
    safeApi(() => api.carPerformance(sessionId)),
    safeApi(() => api.pacePrediction(sessionId))
  ]);

  // Required artifacts, checked in the order the dashboard needs them.
  if (!summary.ok) return artifactFailure(summary);
  if (!drivers.ok) return artifactFailure(drivers);
  if (!laps.ok) return artifactFailure(laps);
  if (!lapTimes.ok) return artifactFailure(lapTimes);
  if (!racePace.ok) return artifactFailure(racePace);
  if (!tyreDegradation.ok) return artifactFailure(tyreDegradation);
  if (!stints.ok) return artifactFailure(stints);
  if (!pitStops.ok) return artifactFailure(pitStops);
  if (!weather.ok) return artifactFailure(weather);
  if (!raceControl.ok) return artifactFailure(raceControl);
  if (!results.ok) return artifactFailure(results);
  if (!telemetryIndex.ok) return artifactFailure(telemetryIndex);
  if (!positionReplay.ok) return artifactFailure(positionReplay);

  const telemetryComparison = await initialTelemetryComparison(api, sessionId, telemetryIndex.data);
  if (!telemetryComparison.ok) {
    return { ok: false, stage: "telemetry", failure: telemetryComparison };
  }

  return {
    ok: true,
    data: {
      summary: summary.data,
      drivers: drivers.data,
      laps: laps.data,
      lapTimes: lapTimes.data,
      racePace: racePace.data,
      tyreDegradation: tyreDegradation.data,
      stints: stints.data,
      pitStops: pitStops.data,
      weather: weather.data,
      raceControl: raceControl.data,
      results: results.data,
      telemetryComparison: telemetryComparison.data,
      telemetryIndex: telemetryIndex.data,
      positionReplay: positionReplay.data,
      idealLaps: idealLaps.ok ? idealLaps.data : null,
      teammateComparison: teammateComparison.ok ? teammateComparison.data : null,
      strategy: strategy.ok ? strategy.data : null,
      trackDominance: trackDominance.ok ? trackDominance.data : null,
      cornerAnalysis: cornerAnalysis.ok ? cornerAnalysis.data : null,
      carPerformance: carPerformance.ok ? carPerformance.data : null,
      pacePrediction: pacePrediction.ok ? pacePrediction.data : null
    }
  };
}

function artifactFailure(failure: ApiFailure): SessionDashboardLoad {
  return { ok: false, stage: "artifacts", failure };
}

async function initialTelemetryComparison(
  api: StaticApi,
  sessionId: string,
  telemetryIndex: TelemetryIndex | null
): Promise<ApiResult<TelemetryComparison | EmptyStateResponse>> {
  if (!telemetryIndex?.laps.length) {
    return {
      ok: true,
      data: {
        reason: "No telemetry lap artifacts are available for this session.",
        action: "Generate telemetry artifacts to enable driver and lap comparisons.",
        details: {}
      }
    };
  }

  const firstLap = telemetryIndex.laps[0];
  const secondLap =
    telemetryIndex.laps.find((lap) => lap.driver_code !== firstLap.driver_code) ||
    telemetryIndex.laps[1] ||
    null;

  if (!secondLap) {
    return {
      ok: true,
      data: {
        reason: "Only one telemetry lap artifact is available for this session.",
        action: "Generate at least two telemetry lap artifacts to enable comparison.",
        details: {}
      }
    };
  }

  return safeApi<TelemetryComparison | EmptyStateResponse>(() =>
    api.telemetryCompare(
      sessionId,
      firstLap.driver_code,
      firstLap.lap_number,
      secondLap.driver_code,
      secondLap.lap_number
    )
  );
}
