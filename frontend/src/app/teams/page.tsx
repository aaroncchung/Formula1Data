import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge } from "@/components/session/Badges";
import { api, safeApi } from "@/lib/api-server";
import { DEFAULT_SESSION_ID } from "@/lib/constants";

export default async function TeamsPage() {
  const drivers = await safeApi(() => api.drivers(DEFAULT_SESSION_ID));
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
      <PageHeader title="Teams" description="Team color references are used only where provided by the data source." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {teams.map((team) => (
          <div key={team.name} className="rounded border border-line bg-panel p-5">
            <div className="h-2 rounded" style={{ backgroundColor: team.color || "#64748b" }} />
            <div className="mt-4 text-xl font-black text-white">{team.name}</div>
            <div className="mt-4 space-y-2">
              {team.drivers.map((driver) => (
                <DriverBadge key={driver.code} code={driver.code} color={team.color} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
