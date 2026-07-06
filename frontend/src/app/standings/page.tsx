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

  const catalog = await safeApi(() => api.catalog());
  if (!catalog.ok) {
    return <ErrorState title="Could not load standings" detail={`${catalog.error.message}: ${catalog.apiBaseUrl}`} />;
  }

  const year = primarySession.data.year;
  const pointSessions = catalog.data.sessions.filter(
    (s) => s.year === year && s.status === "available" && ["R", "S"].includes(s.type.toUpperCase())
  );

  const resultsResponses = await Promise.all(pointSessions.map((s) => safeApi(() => api.results(s.session_id))));
  const driversResponses = await Promise.all(pointSessions.map((s) => safeApi(() => api.drivers(s.session_id))));

  // aggregate drivers
  const driverMap = new Map<string, any>();
  for (const resp of driversResponses) {
    if (resp.ok) {
      for (const d of resp.data) {
        if (!driverMap.has(d.code)) {
          driverMap.set(d.code, d);
        }
      }
    }
  }

  // aggregate points
  const pointsMap = new Map<string, number>();
  for (const resp of resultsResponses) {
    if (resp.ok) {
      for (const r of resp.data) {
        if (r.points) {
          pointsMap.set(r.driver_code, (pointsMap.get(r.driver_code) || 0) + r.points);
        }
      }
    }
  }

  // sort drivers by points
  const standings = Array.from(driverMap.values())
    .map((d) => ({
      driver_code: d.code,
      points: pointsMap.get(d.code) || 0,
      team: d.team
    }))
    .sort((a, b) => b.points - a.points)
    .map((row, index) => ({ ...row, position: index + 1 }));

  const colors = Object.fromEntries(Array.from(driverMap.values()).map((d) => [d.code, d.team.color]));

  return (
    <div>
      <PageHeader title={`${year} Season Standings`} description={`Cumulative points across all available sessions for ${year}.`} />
      <DataTable
        rows={standings}
        columns={[
          { key: "pos", header: "Pos", align: "right", render: (row) => row.position },
          { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
          { key: "points", header: "Pts", align: "right", render: (row) => row.points }
        ]}
      />
    </div>
  );
}
