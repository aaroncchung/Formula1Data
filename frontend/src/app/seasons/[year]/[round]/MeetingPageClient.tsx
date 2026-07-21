"use client";

import Link from "next/link";
import { useCallback } from "react";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { api } from "@/lib/api";
import { sessionHref } from "@/lib/season-routes";
import { useRuntimeData } from "@/lib/use-runtime-data";

export function MeetingPageClient({ year, round }: { year: number; round: number }) {
  const load = useCallback(async () => {
    const [sessions, meetings] = await Promise.all([api.sessions(year, round), api.meetings(year)]);
    return { sessions, meeting: meetings.find((item) => item.round === round) || null };
  }, [round, year]);
  const state = useRuntimeData(load);
  if (state.state === "loading") return <LoadingState label={`Loading round ${round} sessions`} />;
  if (state.state === "error") return <ErrorState title="Could not load sessions" detail={state.detail} />;

  const { sessions, meeting } = state.data;
  const sessionCodes = meeting?.sessions_available.length ? meeting.sessions_available : ["FP1", "FP2", "FP3", "Q", "R"];
  return (
    <div>
      <PageHeader title={`Round ${round} Sessions`} description="Open a published session dashboard or ingest missing data." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {sessionCodes.map((code) => {
          const session = sessions.find((item) => item.type.toUpperCase() === code);
          return (
            <Link key={code} href={sessionHref(year, round, code)} className="rounded border border-line bg-panel p-5 hover:border-redline/60">
              <div className="text-3xl font-black text-white">{code}</div>
              <div className="mt-2 text-sm text-slate-400">{session?.name || "Not generated"}</div>
              <div className={`mt-4 text-xs font-bold uppercase ${session ? "text-aqua" : "text-amber"}`}>{session ? session.status : "Queue available"}</div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
