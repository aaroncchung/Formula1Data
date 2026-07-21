"use client";

import Link from "next/link";
import { useCallback } from "react";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { api } from "@/lib/api";
import { compactDate } from "@/lib/format";
import { meetingHref } from "@/lib/season-routes";
import { useRuntimeData } from "@/lib/use-runtime-data";

export function SeasonPageClient({ year }: { year: number }) {
  const load = useCallback(() => api.meetings(year), [year]);
  const state = useRuntimeData(load);
  if (state.state === "loading") return <LoadingState label={`Loading ${year} meetings`} />;
  if (state.state === "error") return <ErrorState title="Could not load meetings" detail={state.detail} />;
  return (
    <div>
      <PageHeader title={`${year} Season`} description="Meetings and sessions available for analysis." />
      <div className="grid gap-4 xl:grid-cols-2">
        {state.data.map((meeting) => (
          <Link key={meeting.meeting_id} href={meetingHref(meeting.year, meeting.round)} className="rounded border border-line bg-panel p-5 hover:border-redline/60">
            <div className="flex items-start justify-between gap-4">
              <div><div className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Round {meeting.round}</div><div className="mt-2 text-xl font-black text-white">{meeting.name}</div><div className="mt-1 text-sm text-slate-400">{meeting.circuit.name}, {meeting.country}</div></div>
              <div className="text-right text-sm text-slate-400">{compactDate(meeting.start_date)}</div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">{meeting.sessions_available.map((session) => <span key={session} className="rounded border border-line bg-white/[0.03] px-2 py-1 text-xs text-slate-300">{session}</span>)}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
