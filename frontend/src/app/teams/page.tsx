import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge } from "@/components/session/Badges";
import { api, safeApi } from "@/lib/api-server";

export default async function TeamsPage() {
  const primarySession = await safeApi(() => api.primarySession());
  if (!primarySession.ok) {
    return <ErrorState title="Could not load teams" detail={`${primarySession.error.message}: ${primarySession.apiBaseUrl}`} />;
  }
  const [drivers, results, racePace] = await Promise.all([
    safeApi(() => api.drivers(primarySession.data.session_id)),
    safeApi(() => api.results(primarySession.data.session_id)),
    safeApi(() => api.racePace(primarySession.data.session_id))
  ]);
  if (!drivers.ok) {
    return <ErrorState title="Could not load teams" detail={`${drivers.error.message}: ${drivers.apiBaseUrl}`} />;
  }
  const teams = Object.values(
    drivers.data.reduce<Record<string, { name: string; color?: string | null; drivers: typeof drivers.data }>>(
      (acc, driver) => {
        const key = driver.team.name;
        acc[key] = acc[key] || { name: driver.team.name, color: driver.team.color, drivers: [] };
        acc[key].drivers.push(driver);
        return acc;
      },
      {}
    )
  );
  return (
    <div>
      <PageHeader title="Teams" description={`Latest session line-ups with combined points, best finish, and clean-lap pace coverage.`} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {teams.map((team) => (
          <div key={team.name} className="surface p-5">
            <div className="h-2 rounded" style={{ backgroundColor: team.color || "#64748b" }} />
            <div className="mt-4 text-xl font-black text-white">{team.name}</div>
            <div className="mt-4 space-y-2">
              {team.drivers.map((driver) => (
                <DriverBadge key={driver.code} code={driver.code} color={team.color} />
              ))}
            </div>
            <div className="mt-5 grid grid-cols-3 gap-2 border-t border-line/70 pt-4 text-center">
              <TeamStat label="Points" value={results.ok ? team.drivers.reduce((sum, driver) => sum + (results.data.find((row) => row.driver_code === driver.code)?.points || 0), 0).toFixed(0) : "--"} />
              <TeamStat label="Best finish" value={results.ok ? `P${Math.min(...team.drivers.map((driver) => results.data.find((row) => row.driver_code === driver.code)?.position || 99))}` : "--"} />
              <TeamStat label="Pace laps" value={racePace.ok ? String(team.drivers.reduce((sum, driver) => sum + (racePace.data.drivers.find((row) => row.driver_code === driver.code)?.lap_count || 0), 0)) : "--"} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TeamStat({ label, value }: { label: string; value: string }) {
  return <div><div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">{label}</div><div className="mt-1 font-mono text-sm font-bold text-white">{value}</div></div>;
}
