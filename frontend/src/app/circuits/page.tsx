import { MapPin } from "lucide-react";
import Link from "next/link";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { api, safeApi } from "@/lib/api-server";

export default async function CircuitsPage() {
  const catalog = await safeApi(() => api.catalog());
  if (!catalog.ok) {
    return <ErrorState title="Could not load circuits" detail={`${catalog.error.message}: ${catalog.apiBaseUrl}`} />;
  }
  const circuits = Array.from(
    catalog.data.meetings.reduce((map, meeting) => {
      const entry = map.get(meeting.circuit.circuit_id) || { circuit: meeting.circuit, meetings: [] as typeof catalog.data.meetings };
      entry.meetings.push(meeting);
      map.set(meeting.circuit.circuit_id, entry);
      return map;
    }, new Map<string, { circuit: (typeof catalog.data.meetings)[number]["circuit"]; meetings: typeof catalog.data.meetings }>()).values()
  ).sort((a, b) => a.circuit.name.localeCompare(b.circuit.name));
  return (
    <div>
      <PageHeader title="Circuits" description={`${circuits.length} unique venues across all processed season calendars.`} />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {circuits.map(({ circuit, meetings }) => {
          const latest = [...meetings].sort((a, b) => b.year - a.year || b.round - a.round)[0];
          const years = [...new Set(meetings.map((meeting) => meeting.year))].sort((a, b) => b - a);
          return (
          <Link key={circuit.circuit_id} href={`/seasons/${latest.year}/${latest.round}`} className="surface group p-5 transition hover:-translate-y-0.5 hover:border-redline/50">
            <div className="flex items-start justify-between gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-md border border-line bg-carbon/50 text-redline"><MapPin size={18} aria-hidden="true" /></div>
              <div className="text-right"><div className="font-mono text-sm font-bold text-white">{meetings.length}</div><div className="text-[10px] uppercase tracking-wider text-slate-600">meetings</div></div>
            </div>
            <div className="mt-4 text-xl font-black text-white transition group-hover:text-redline">{circuit.name}</div>
            <div className="mt-1 text-sm text-slate-400">{circuit.location || latest.country}, {circuit.country}</div>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {years.slice(0, 6).map((year) => <span key={year} className="rounded border border-line/70 bg-carbon/40 px-2 py-1 font-mono text-[11px] text-slate-400">{year}</span>)}
              {years.length > 6 ? <span className="px-2 py-1 text-[11px] text-slate-600">+{years.length - 6}</span> : null}
            </div>
          </Link>
        );})}
      </div>
    </div>
  );
}
