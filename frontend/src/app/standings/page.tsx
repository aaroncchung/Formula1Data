"use client";

import { useCallback } from "react";

import { DataTable } from "@/components/data-table/DataTable";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { DriverBadge } from "@/components/session/Badges";
import { api } from "@/lib/api";
import { useRuntimeData } from "@/lib/use-runtime-data";
import type { Driver } from "@/types/domain";

export default function StandingsPage() {
  const load = useCallback(async () => {
    const [primarySession, catalog] = await Promise.all([api.primarySession(), api.catalog()]);
    const year = primarySession.year;
    const pointSessions = catalog.sessions.filter(
      (session) => session.year === year && session.status !== "missing" && ["R", "S"].includes(session.type.toUpperCase())
    );
    const [resultsResponses, driversResponses] = await Promise.all([
      Promise.all(pointSessions.map((session) => api.results(session.session_id).catch(() => []))),
      Promise.all(pointSessions.map((session) => api.drivers(session.session_id).catch(() => [])))
    ]);

    const driverMap = new Map<string, Driver>();
    for (const drivers of driversResponses) {
      for (const driver of drivers) if (!driverMap.has(driver.code)) driverMap.set(driver.code, driver);
    }
    const pointsMap = new Map<string, { points: number; wins: number; podiums: number; starts: number }>();
    for (const results of resultsResponses) {
      for (const result of results) {
        const aggregate = pointsMap.get(result.driver_code) || { points: 0, wins: 0, podiums: 0, starts: 0 };
        aggregate.points += result.points || 0;
        aggregate.wins += result.position === 1 ? 1 : 0;
        aggregate.podiums += result.position <= 3 ? 1 : 0;
        aggregate.starts += 1;
        pointsMap.set(result.driver_code, aggregate);
      }
    }
    const standings = Array.from(driverMap.values())
      .map((driver) => ({
        driver_code: driver.code,
        points: pointsMap.get(driver.code)?.points || 0,
        wins: pointsMap.get(driver.code)?.wins || 0,
        podiums: pointsMap.get(driver.code)?.podiums || 0,
        starts: pointsMap.get(driver.code)?.starts || 0,
        team: driver.team
      }))
      .sort((a, b) => b.points - a.points || b.wins - a.wins || b.podiums - a.podiums)
      .map((row, index) => ({ ...row, position: index + 1 }));
    return { year, pointSessionCount: pointSessions.length, standings, driverMap };
  }, []);
  const state = useRuntimeData(load);

  if (state.state === "loading") return <LoadingState label="Loading current season results" />;
  if (state.state === "error") return <ErrorState title="Could not load standings" detail={state.detail} />;

  const { year, pointSessionCount, standings, driverMap } = state.data;
  const colors = Object.fromEntries(Array.from(driverMap.values()).map((driver) => [driver.code, driver.team.color]));
  return (
    <div>
      <PageHeader title={`${year} Season Standings`} description={`Cumulative points across ${pointSessionCount} available race and sprint sessions. Ties sort by wins, then podiums.`} />
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
      <div>{teams.map((row, index) => (
        <div key={row.team.team_id} className="grid grid-cols-[32px_5px_1fr_auto] items-center gap-3 border-b border-line/60 px-4 py-3 last:border-0">
          <span className="font-mono text-xs text-slate-500">{index + 1}</span><span className="h-7 rounded-full" style={{ backgroundColor: row.team.color || "#64748b" }} /><span className="truncate text-sm font-semibold text-slate-200">{row.team.name}</span><span className="font-mono text-sm font-black text-white">{row.points}</span>
        </div>
      ))}</div>
    </section>
  );
}
