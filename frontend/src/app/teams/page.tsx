"use client";

import { useCallback } from "react";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge } from "@/components/session/Badges";
import { api } from "@/lib/api";
import { useRuntimeData } from "@/lib/use-runtime-data";

export default function TeamsPage() {
  const load = useCallback(async () => {
    const session = await api.primarySession();
    const [drivers, results, racePace] = await Promise.all([api.drivers(session.session_id), api.results(session.session_id).catch(() => []), api.racePace(session.session_id).catch(() => null)]);
    return { drivers, results, racePace };
  }, []);
  const state = useRuntimeData(load);
  if (state.state === "loading") return <LoadingState label="Loading current team artifacts" />;
  if (state.state === "error") return <ErrorState title="Could not load teams" detail={state.detail} />;
  const { drivers, results, racePace } = state.data;
  const teams = Object.values(drivers.reduce<Record<string, { name: string; color?: string | null; drivers: typeof drivers }>>((acc, driver) => {
    const key = driver.team.name;
    acc[key] ||= { name: key, color: driver.team.color, drivers: [] };
    acc[key].drivers.push(driver);
    return acc;
  }, {}));
  return <div><PageHeader title="Teams" description="Latest session line-ups with combined points, best finish, and clean-lap pace coverage." /><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{teams.map((team) => <div key={team.name} className="surface p-5"><div className="h-2 rounded" style={{ backgroundColor: team.color || "#64748b" }} /><div className="mt-4 text-xl font-black text-white">{team.name}</div><div className="mt-4 space-y-2">{team.drivers.map((driver) => <DriverBadge key={driver.code} code={driver.code} color={team.color} />)}</div><div className="mt-5 grid grid-cols-3 gap-2 border-t border-line/70 pt-4 text-center"><TeamStat label="Points" value={team.drivers.reduce((sum, driver) => sum + (results.find((row) => row.driver_code === driver.code)?.points || 0), 0).toFixed(0)} /><TeamStat label="Best finish" value={results.length ? `P${Math.min(...team.drivers.map((driver) => results.find((row) => row.driver_code === driver.code)?.position || 99))}` : "--"} /><TeamStat label="Pace laps" value={racePace ? String(team.drivers.reduce((sum, driver) => sum + (racePace.drivers.find((row) => row.driver_code === driver.code)?.lap_count || 0), 0)) : "--"} /></div></div>)}</div></div>;
}

function TeamStat({ label, value }: { label: string; value: string }) {
  return <div><div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">{label}</div><div className="mt-1 font-mono text-sm font-bold text-white">{value}</div></div>;
}
