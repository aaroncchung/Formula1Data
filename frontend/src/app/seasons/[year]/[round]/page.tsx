import Link from "next/link";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { api, safeApi } from "@/lib/api-server";

export const dynamicParams = false;

export async function generateStaticParams() {
  const catalog = await api.catalog();
  const rounds = new Map<string, { year: string; round: string }>();
  for (const meeting of catalog.meetings) {
    rounds.set(`${meeting.year}-${meeting.round}`, {
      year: String(meeting.year),
      round: String(meeting.round)
    });
  }
  return Array.from(rounds.values());
}

export default async function MeetingPage({ params }: { params: Promise<{ year: string; round: string }> }) {
  const { year: yearParam, round: roundParam } = await params;
  const year = Number(yearParam);
  const round = Number(roundParam);
  const [sessions, meetings] = await Promise.all([
    safeApi(() => api.sessions(year, round)),
    safeApi(() => api.meetings(year))
  ]);
  if (!sessions.ok) {
    return <ErrorState title="Could not load sessions" detail={`${sessions.error.message}: ${sessions.apiBaseUrl}`} />;
  }
  if (!meetings.ok) {
    return <ErrorState title="Could not load sessions" detail={`${meetings.error.message}: ${meetings.apiBaseUrl}`} />;
  }
  const meeting = meetings.data.find((item) => item.round === round);
  const sessionCodes = meeting?.sessions_available.length ? meeting.sessions_available : ["FP1", "FP2", "FP3", "Q", "R"];
  return (
    <div>
      <PageHeader title={`Round ${round} Sessions`} description="Open an ingested session dashboard or ingest missing data." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {sessionCodes.map((code) => {
          const session = sessions.data.find((item) => item.type.toUpperCase() === code);
          const href = `/seasons/${year}/${round}/${code}`;
          const content = (
            <>
              <div className="text-3xl font-black text-white">{code}</div>
              <div className="mt-2 text-sm text-slate-400">{session?.name || "Not ingested"}</div>
              <div className={`mt-4 text-xs font-bold uppercase ${session ? "text-aqua" : "text-amber"}`}>
                {session ? session.status : "Awaiting data"}
              </div>
            </>
          );
          if (!session) {
            return (
              <div key={code} className="rounded border border-line bg-panel p-5 opacity-70">
                {content}
              </div>
            );
          }
          return (
            <Link key={code} href={href} className="rounded border border-line bg-panel p-5 hover:border-redline/60">
              {content}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
