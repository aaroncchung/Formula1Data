import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { SessionIngestionPanel } from "@/components/session/SessionIngestionPanel";
import { SessionTabs } from "@/components/session/SessionTabs";
import { api, isApiFailure, safeApi } from "@/lib/api-server";

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
    telemetryComparison,
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
    safeApi(() => api.telemetryCompare(sessionId, "VER", 6, "LEC", 7)),
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
    telemetryComparison,
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
    !telemetryComparison.ok ||
    !positionReplay.ok
  ) {
    return null;
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
