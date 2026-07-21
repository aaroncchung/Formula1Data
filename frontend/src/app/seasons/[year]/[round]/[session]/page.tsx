import { SessionIngestionPanel } from "@/components/session/SessionIngestionPanel";
import { loadRouteCatalog } from "@/lib/route-catalog";

export const dynamicParams = false;

export default async function SessionPage({ params }: { params: Promise<{ year: string; round: string; session: string }> }) {
  const route = await params;
  const year = Number(route.year);
  const round = Number(route.round);
  return (
    <SessionIngestionPanel
      key={`${year}-${round}-${route.session}`}
      year={year}
      round={round}
      session={route.session}
      staticCommand={`python -m pipeline ingest-session --year ${year} --event ${round} --session ${route.session}`}
    />
  );
}

export async function generateStaticParams() {
  const catalog = await loadRouteCatalog();
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
