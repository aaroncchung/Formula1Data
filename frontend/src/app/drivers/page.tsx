import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge, TeamColorPill } from "@/components/session/Badges";
import { api, safeApi } from "@/lib/api-server";
import { DEFAULT_SESSION_ID } from "@/lib/constants";

export default async function DriversPage() {
  const drivers = await safeApi(() => api.drivers(DEFAULT_SESSION_ID));
  if (!drivers.ok) {
    return <ErrorState title="Could not load drivers" detail={`${drivers.error.message}: ${drivers.apiBaseUrl}`} />;
  }
  return (
    <div>
      <PageHeader title="Drivers" description="Driver metadata loaded from static session artifacts." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {drivers.data.map((driver) => (
          <div key={driver.code} className="rounded border border-line bg-panel p-5">
            <div className="flex items-start justify-between gap-3">
              <DriverBadge code={driver.code} color={driver.team.color} />
              <div className="font-mono text-sm text-slate-500">#{driver.number || "--"}</div>
            </div>
            <div className="mt-3 text-xl font-black text-white">{driver.full_name}</div>
            <div className="mt-4">
              <TeamColorPill name={driver.team.name} color={driver.team.color} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
