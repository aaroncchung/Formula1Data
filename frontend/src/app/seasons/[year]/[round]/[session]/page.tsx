import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { SessionIngestionPanel } from "@/components/session/SessionIngestionPanel";
import { SessionTabs } from "@/components/session/SessionTabs";
import { api, safeApi } from "@/lib/api-server";
import { loadSessionDashboard } from "@/lib/session-dashboard";

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
  const dashboard = await loadSessionDashboard(api, sessionId);

  if (!dashboard.ok && dashboard.stage === "telemetry") {
    return (
      <ErrorState
        title="Could not load telemetry"
        detail={`${dashboard.failure.error.message}: ${dashboard.failure.apiBaseUrl}`}
      />
    );
  }

  if (!dashboard.ok) {
    const year = Number(routeParams.year);
    const round = Number(routeParams.round);
    const meetings = await safeApi(() => api.meetings(year));
    const meeting = meetings.ok ? meetings.data.find((item) => item.round === round) : null;
    const command = `python -m pipeline ingest-session --year ${routeParams.year} --event "${
      meeting?.name || "Grand Prix"
    }" --session ${routeParams.session}`;
    return (
      <div className="space-y-5">
        <ErrorState
          title="Session is not available"
          detail={`${dashboard.failure.error.message}: ${dashboard.failure.apiBaseUrl}`}
        />
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

  const summary = dashboard.data.summary;
  return (
    <div>
      <PageHeader
        eyebrow={`${summary.year} Round ${summary.round}`}
        title={`${summary.meeting} - ${summary.session}`}
        description={`${summary.circuit}, ${summary.country}. ${summary.weather_summary}.`}
      />
      <SessionTabs {...dashboard.data} />
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
