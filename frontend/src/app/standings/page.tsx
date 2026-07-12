import { DataTable } from "@/components/data-table/DataTable";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge } from "@/components/session/Badges";
import { api, safeApi } from "@/lib/api-server";
import type { Driver } from "@/types/domain";

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
    (s) => s.year === year && s.status !== "missing" && ["R", "S"].includes(s.type.toUpperCase())
  );

  const resultsResponses = await Promise.all(pointSessions.map((s) => safeApi(() => api.results(s.session_id))));
  const driversResponses = await Promise.all(pointSessions.map((s) => safeApi(() => api.drivers(s.session_id))));

  const driverMap = new Map<string, Driver>();
  for (const resp of driversResponses) {
    if (resp.ok) {
      for (const d of resp.data) {
        if (!driverMap.has(d.code)) {
          driverMap.set(d.code, d);
        }
      }
    }
  }

  const pointsMap = new Map<string, { points: number; wins: number; podiums: number; starts: number }>();
  for (const resp of resultsResponses) {
    if (resp.ok) {
      for (const r of resp.data) {
        const aggregate = pointsMap.get(r.driver_code) || { points: 0, wins: 0, podiums: 0, starts: 0 };
        aggregate.points += r.points || 0;
        aggregate.wins += r.position === 1 ? 1 : 0;
        aggregate.podiums += r.position <= 3 ? 1 : 0;
        aggregate.starts += 1;
        pointsMap.set(r.driver_code, aggregate);
      }
    }
  }

  const standings = Array.from(driverMap.values())
    .map((d) => ({
      driver_code: d.code,
      points: pointsMap.get(d.code)?.points || 0,
      wins: pointsMap.get(d.code)?.wins || 0,
      podiums: pointsMap.get(d.code)?.podiums || 0,
      starts: pointsMap.get(d.code)?.starts || 0,
      team: d.team
    }))
    .sort((a, b) => b.points - a.points || b.wins - a.wins || b.podiums - a.podiums)
    .map((row, index) => ({ ...row, position: index + 1 }));

  const colors = Object.fromEntries(Array.from(driverMap.values()).map((d) => [d.code, d.team.color]));

  return (
    <div>
      <PageHeader title={`${year} Season Standings`} description={`Cumulative points across ${pointSessions.length} available race and sprint sessions. Ties sort by wins, then podiums.`} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.6fr)]">
        <DataTable
          rows={standings}
          columns={[
            { key: "pos", header: "Pos", align: "right", render: (row) => <span className="font-mono font-black">{row.position}</span> },
            { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
            { key: "team", header: "Team", render: (row) => row.team.name },
            { key: "wins", header: "Wins", align: "right", render: (row) => row.wins },
            { key: "podiums", header: "Podiums", align: "right", render: (row) => row.podiums },
            { key: "starts", header: "Starts", align: "right", render: (row) => row.starts },
            { key: "points", header: "Pts", align: "right", render: (row) => <span className="font-mono font-black text-white">{row.points}</span> }
          ]}
        />
        <ConstructorStandings standings={standings} />
      </div>
    </div>
  );
}

function ConstructorStandings({ standings }: { standings: Array<{ team: Driver["team"]; points: number; wins: number }> }) {
  const teams = Array.from(standings.reduce((map, row) => {
    const team = map.get(row.team.team_id) || { team: row.team, points: 0, wins: 0 };
    team.points += row.points;
    team.wins += row.wins;
    map.set(row.team.team_id, team);
    return map;
  }, new Map<string, { team: Driver["team"]; points: number; wins: number }>()).values()).sort((a, b) => b.points - a.points || b.wins - a.wins);
  return (
    <section className="surface self-start overflow-hidden">
      <div className="border-b border-line/70 p-4"><h2 className="font-bold text-white">Constructors</h2><p className="mt-1 text-xs text-slate-500">Derived from available result artifacts.</p></div>
      <div>
        {teams.map((row, index) => (
          <div key={row.team.team_id} className="grid grid-cols-[32px_5px_1fr_auto] items-center gap-3 border-b border-line/60 px-4 py-3 last:border-0">
            <span className="font-mono text-xs text-slate-500">{index + 1}</span>
            <span className="h-7 rounded-full" style={{ backgroundColor: row.team.color || "#64748b" }} />
            <span className="truncate text-sm font-semibold text-slate-200">{row.team.name}</span>
            <span className="font-mono text-sm font-black text-white">{row.points}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
