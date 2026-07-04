import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { SessionIngestionPanel } from "@/components/session/SessionIngestionPanel";
import { SessionTabs } from "@/components/session/SessionTabs";
import { api, isApiFailure, safeApi } from "@/lib/api-server";
import type { EmptyStateResponse, TelemetryComparison } from "@/types/domain";

export const dynamicParams = false;

function sessionIdFromParams(year: string, round: string, session: string): string {
  return `${year}-${String(round).padStart(2, "0")}-${session.toLowerCase()}`;
}

export default async function SessionPage({
  params
}: {
  params: Promise<{ year: string; round: string; session: string }>;
}) {
  const routeParams = await params;
  const sessionId = sessionIdFromParams(routeParams.year, routeParams.round, routeParams.session);
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
    positionReplay
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
    safeApi(() => api.positionReplay(sessionId))
  ]);

  const all = [
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
    positionReplay
  ];
  const failed = all.find(isApiFailure);
  if (failed) {
    const year = Number(routeParams.year);
    const round = Number(routeParams.round);
    const meetings = await safeApi(() => api.meetings(year));
    const meeting = meetings.ok ? meetings.data.find((item) => item.round === round) : null;
    const command = `python -m pipeline ingest-session --year ${routeParams.year} --event "${
      meeting?.name || "Grand Prix"
    }" --session ${routeParams.session}`;
    return (
      <div className="space-y-5">
        <ErrorState title="Session is not available" detail={`${failed.error.message}: ${failed.apiBaseUrl}`} />
        <SessionIngestionPanel
          year={year}
          round={round}
          session={routeParams.session}
          meetingId={meeting?.meeting_id}
          meetingName={meeting?.name}
          scheduledStart={meeting?.start_date}
          staticCommand={command}
        />
      </div>
    );
  }

  if (
    !summary.ok ||
    !drivers.ok ||
    !laps.ok ||
    !lapTimes.ok ||
    !racePace.ok ||
    !tyreDegradation.ok ||
    !stints.ok ||
    !pitStops.ok ||
    !weather.ok ||
    !raceControl.ok ||
    !results.ok ||
    !telemetryIndex.ok ||
    !positionReplay.ok
  ) {
    return null;
  }

  const telemetryComparison = await initialTelemetryComparison(sessionId, telemetryIndex.data);
  if (!telemetryComparison.ok) {
    return <ErrorState title="Could not load telemetry" detail={`${telemetryComparison.error.message}: ${telemetryComparison.apiBaseUrl}`} />;
  }

  return (
    <div>
      <PageHeader
        eyebrow={`${summary.data.year} Round ${summary.data.round}`}
        title={`${summary.data.meeting} - ${summary.data.session}`}
        description={`${summary.data.circuit}, ${summary.data.country}. ${summary.data.weather_summary}.`}
      />
      <SessionTabs
        summary={summary.data}
        drivers={drivers.data}
        laps={laps.data}
        lapTimes={lapTimes.data}
        racePace={racePace.data}
        tyreDegradation={tyreDegradation.data}
        stints={stints.data}
        pitStops={pitStops.data}
        weather={weather.data}
        raceControl={raceControl.data}
        results={results.data}
        telemetryComparison={telemetryComparison.data}
        positionReplay={positionReplay.data}
      />
    </div>
  );
}

export async function generateStaticParams() {
  const catalog = await api.catalog();
  const params = new Map<string, { year: string; round: string; session: string }>();
  for (const session of catalog.sessions) {
    params.set(`${session.year}-${session.round}-${session.type}`, {
      year: String(session.year),
      round: String(session.round),
      session: session.type
    });
  }
  for (const meeting of catalog.meetings) {
    for (const code of meeting.sessions_available) {
      params.set(`${meeting.year}-${meeting.round}-${code}`, {
        year: String(meeting.year),
        round: String(meeting.round),
        session: code
      });
    }
  }
  return Array.from(params.values());
}

async function initialTelemetryComparison(
  sessionId: string,
  telemetryIndex: Awaited<ReturnType<typeof api.telemetryIndex>>
) {
  if (!telemetryIndex?.laps.length) {
    return {
      ok: true as const,
      data: telemetryUnavailableState()
    };
  }

  const firstLap = telemetryIndex.laps[0];
  const secondLap =
    telemetryIndex.laps.find((lap) => lap.driver_code !== firstLap.driver_code) ||
    telemetryIndex.laps[1] ||
    null;

  if (!secondLap) {
    return {
      ok: true as const,
      data: {
        reason: "Only one telemetry lap artifact is available for this session.",
        action: "Generate at least two telemetry lap artifacts to enable comparison.",
        details: {}
      } satisfies EmptyStateResponse
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

function telemetryUnavailableState(): EmptyStateResponse {
  return {
    reason: "No telemetry lap artifacts are available for this session.",
    action: "Generate telemetry artifacts to enable driver and lap comparisons.",
    details: {}
  };
}
