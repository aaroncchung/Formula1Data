"use client";

import { useCallback } from "react";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge, TeamColorPill } from "@/components/session/Badges";
import { api } from "@/lib/api";
import { formatMs } from "@/lib/format";
import { useRuntimeData } from "@/lib/use-runtime-data";

export default function DriversPage() {
  const load = useCallback(async () => {
    const session = await api.primarySession();
    const [drivers, results, racePace, idealLaps] = await Promise.all([
      api.drivers(session.session_id), api.results(session.session_id).catch(() => []), api.racePace(session.session_id).catch(() => null), api.idealLaps(session.session_id).catch(() => null)
    ]);
    return { session, drivers, results, racePace, idealLaps };
  }, []);
  const state = useRuntimeData(load);
  if (state.state === "loading") return <LoadingState label="Loading current driver artifacts" />;
  if (state.state === "error") return <ErrorState title="Could not load drivers" detail={state.detail} />;
  const { session, drivers, results, racePace, idealLaps } = state.data;
  return <div><PageHeader title="Drivers" description={`Latest available field with result, pace, and ideal-lap context from ${session.year} round ${session.round}.`} /><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{drivers.map((driver) => {
    const result = results.find((item) => item.driver_code === driver.code);
    const pace = racePace?.drivers.find((item) => item.driver_code === driver.code);
    const ideal = idealLaps?.rows.find((item) => item.driver_code === driver.code);
    return <div key={driver.code} className="surface overflow-hidden p-5"><div className="-mx-5 -mt-5 mb-5 h-1" style={{ backgroundColor: driver.team.color || "#64748b" }} /><div className="flex items-start justify-between gap-3"><DriverBadge code={driver.code} color={driver.team.color} /><div className="font-mono text-sm text-slate-500">#{driver.number || "--"}</div></div><div className="mt-3 text-xl font-black text-white">{driver.full_name}</div><div className="mt-4"><TeamColorPill name={driver.team.name} color={driver.team.color} /></div><div className="mt-5 grid grid-cols-3 gap-2 border-t border-line/70 pt-4 text-center"><DriverStat label="Finish" value={result ? `P${result.position}` : "--"} /><DriverStat label="Median pace" value={formatMs(pace?.median_lap_ms)} /><DriverStat label="Ideal" value={formatMs(ideal?.ideal_lap_ms)} /></div></div>;
  })}</div></div>;
}

function DriverStat({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">{label}</div><div className="mt-1 truncate font-mono text-xs font-bold text-slate-200" title={value}>{value}</div></div>;
}
