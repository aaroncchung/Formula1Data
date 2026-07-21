"use client";

import { MapPin } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { api } from "@/lib/api";
import { meetingHref } from "@/lib/season-routes";
import { useRuntimeData } from "@/lib/use-runtime-data";

export default function CircuitsPage() {
  const load = useCallback(() => api.catalog(), []);
  const state = useRuntimeData(load);
  if (state.state === "loading") return <LoadingState label="Loading current circuit catalog" />;
  if (state.state === "error") return <ErrorState title="Could not load circuits" detail={state.detail} />;
  const catalog = state.data;
  const circuits = Array.from(catalog.meetings.reduce((map, meeting) => {
    const entry = map.get(meeting.circuit.circuit_id) || { circuit: meeting.circuit, meetings: [] as typeof catalog.meetings };
    entry.meetings.push(meeting);
    map.set(meeting.circuit.circuit_id, entry);
    return map;
  }, new Map<string, { circuit: (typeof catalog.meetings)[number]["circuit"]; meetings: typeof catalog.meetings }>()).values()).sort((a, b) => a.circuit.name.localeCompare(b.circuit.name));
  return (
    <div>
      <PageHeader title="Circuits" description={`${circuits.length} unique venues across all published season calendars.`} />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{circuits.map(({ circuit, meetings }) => {
        const latest = [...meetings].sort((a, b) => b.year - a.year || b.round - a.round)[0];
        const years = [...new Set(meetings.map((meeting) => meeting.year))].sort((a, b) => b - a);
        return <Link key={circuit.circuit_id} href={meetingHref(latest.year, latest.round)} className="surface group p-5 transition hover:-translate-y-0.5 hover:border-redline/50">
          <div className="flex items-start justify-between gap-3"><div className="grid h-10 w-10 place-items-center rounded-md border border-line bg-carbon/50 text-redline"><MapPin size={18} aria-hidden="true" /></div><div className="text-right"><div className="font-mono text-sm font-bold text-white">{meetings.length}</div><div className="text-[10px] uppercase tracking-wider text-slate-600">meetings</div></div></div>
          <div className="mt-4 text-xl font-black text-white transition group-hover:text-redline">{circuit.name}</div><div className="mt-1 text-sm text-slate-400">{circuit.location || latest.country}, {circuit.country}</div>
          <div className="mt-4 flex flex-wrap gap-1.5">{years.slice(0, 6).map((year) => <span key={year} className="rounded border border-line/70 bg-carbon/40 px-2 py-1 font-mono text-[11px] text-slate-400">{year}</span>)}{years.length > 6 ? <span className="px-2 py-1 text-[11px] text-slate-600">+{years.length - 6}</span> : null}</div>
        </Link>;
      })}</div>
    </div>
  );
}
