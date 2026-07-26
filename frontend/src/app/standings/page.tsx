import { DataTable } from "@/components/data-table/DataTable";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge } from "@/components/session/Badges";
import { api, safeApi } from "@/lib/api-server";
import type { Driver, Team } from "@/types/domain";

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

  // Sessions are catalog-ordered by (year, round, type), so the last entry seen
  // for a driver is their most recent team. Points are attributed to the team
  // recorded for the session they were scored in, not to a frozen team.
  const driverMap = new Map<string, Driver>();
  const pointsMap = new Map<string, { points: number; wins: number; podiums: number; starts: number }>();
  const teamMap = new Map<string, { team: Team; points: number; wins: number }>();

  pointSessions.forEach((session, index) => {
    const driversResponse = driversResponses[index];
    const resultsResponse = resultsResponses[index];
    const sessionTeams = new Map<string, Team>();
    if (driversResponse.ok) {
      for (const d of driversResponse.data) {
        sessionTeams.set(d.code, d.team);
        driverMap.set(d.code, d);
      }
    }
    if (!resultsResponse.ok) {
      return;
    }
    // Sprints award championship points, but their finishes are not race wins,
    // podiums or starts, so only `R` sessions feed those columns.
    const isRace = session.type.toUpperCase() === "R";
    for (const r of resultsResponse.data) {
      const points = r.points || 0;
      const win = isRace && r.position === 1 ? 1 : 0;
      const aggregate = pointsMap.get(r.driver_code) || { points: 0, wins: 0, podiums: 0, starts: 0 };
      aggregate.points += points;
      aggregate.wins += win;
      aggregate.podiums += isRace && r.position <= 3 ? 1 : 0;
      aggregate.starts += isRace ? 1 : 0;
      pointsMap.set(r.driver_code, aggregate);

      const team = sessionTeams.get(r.driver_code);
      if (team) {
        const constructor = teamMap.get(team.team_id) || { team, points: 0, wins: 0 };
        constructor.team = team;
        constructor.points += points;
        constructor.wins += win;
        teamMap.set(team.team_id, constructor);
      }
    }
  });

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

  const constructors = Array.from(teamMap.values()).sort((a, b) => b.points - a.points || b.wins - a.wins);

  const colors = Object.fromEntries(Array.from(driverMap.values()).map((d) => [d.code, d.team.color]));

  return (
    <div>
      <PageHeader title={`${year} Season Standings`} description={`Cumulative points across ${pointSessions.length} available race and sprint sessions; wins, podiums and starts count races only. Ties sort by wins, then podiums.`} />
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
        <ConstructorStandings teams={constructors} />
      </div>
    </div>
  );
}

function ConstructorStandings({ teams }: { teams: Array<{ team: Team; points: number; wins: number }> }) {
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
