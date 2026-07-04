import { DataTable } from "@/components/data-table/DataTable";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge } from "@/components/session/Badges";
import { api, isApiFailure, safeApi } from "@/lib/api-server";

export default async function StandingsPage() {
  const primarySession = await safeApi(() => api.primarySession());
  if (!primarySession.ok) {
    return <ErrorState title="Could not load standings" detail={`${primarySession.error.message}: ${primarySession.apiBaseUrl}`} />;
  }
  const [results, drivers] = await Promise.all([
    safeApi(() => api.results(primarySession.data.session_id)),
    safeApi(() => api.drivers(primarySession.data.session_id))
  ]);
  const failed = [results, drivers].find(isApiFailure);
  if (failed) {
    return <ErrorState title="Could not load standings" detail={`${failed.error.message}: ${failed.apiBaseUrl}`} />;
  }
  if (!results.ok || !drivers.ok) {
    return null;
  }
  const colors = Object.fromEntries(drivers.data.map((driver) => [driver.code, driver.team.color]));
  return (
    <div>
      <PageHeader title="Standings" description="Session result table from processed timing artifacts." />
      <DataTable
        rows={results.data}
        columns={[
          { key: "pos", header: "Pos", align: "right", render: (row) => row.position },
          { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
          { key: "grid", header: "Grid", align: "right", render: (row) => row.grid ?? "--" },
          { key: "gap", header: "Gap", align: "right", render: (row) => row.gap || "--" },
          { key: "points", header: "Pts", align: "right", render: (row) => row.points ?? 0 }
        ]}
      />
    </div>
  );
}
