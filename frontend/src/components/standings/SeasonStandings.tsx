"use client";

import clsx from "clsx";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { LoadFailure } from "@/components/published/LoadFailure";
import { usePublishedIndex } from "@/components/calendar/usePublishedIndex";
import { DataTable } from "@/components/data-table/DataTable";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { usePublishedStandings } from "@/components/standings/usePublishedStandings";
import { findSeason, seasonOverviews } from "@/lib/calendar";
import type { ConstructorStanding, IndexSeason, PublishedIndex, Standings } from "@/lib/published/types";
import { standingsHref, yearParam } from "@/lib/routes";
import { defaultStandingsYear, driverName, roundLabel, standingsRounds } from "@/lib/standings-view";
import type { StandingsRound } from "@/lib/standings-view";

const SOURCE_NOTE = "Taken whole from Jolpica when the data was published; nothing is added up from session results.";

/**
 * `/standings?year=2026`: the championship tables as published.
 *
 * The page used to add up the points of the sessions the site held, which was
 * wrong for 12 of 22 drivers (AR-15). It now shows the published tables and
 * says which round they are after.
 */
export function SeasonStandings() {
  const param = yearParam(useSearchParams());
  const calendar = usePublishedIndex();
  const index = calendar.state.status === "ready" ? calendar.state.index : null;

  if (param.status === "invalid") {
    return (
      <div>
        <PageHeader title="Season Standings" />
        <EmptyState
          title="Not a season"
          detail={`The address names the season "${param.raw}", and a season is a year, as in ${standingsHref(2026)}.`}
        />
        {index ? <SeasonLinks index={index} current={null} /> : null}
      </div>
    );
  }

  // The season in the address is shown whether or not the calendar could be
  // read: the standings are their own file. Only choosing a season for the
  // reader needs the calendar.
  const year = param.status === "ok" ? param.value : index ? defaultStandingsYear(index) : null;
  if (year !== null) {
    return <StandingsOfYear year={year} index={index} />;
  }
  return (
    <div>
      <PageHeader title="Season Standings" />
      {calendar.state.status === "loading" ? <LoadingState label="Loading the calendar" /> : null}
      {calendar.state.status === "failed" ? (
        <LoadFailure failure={calendar.state.failure} onRetry={calendar.retry} />
      ) : null}
      {calendar.state.status === "ready" ? (
        <EmptyState
          title="The published calendar has no seasons"
          detail="The calendar was read, and it lists no season yet, so there is no season to show standings for."
        />
      ) : null}
    </div>
  );
}

function StandingsOfYear({ year, index }: { year: number; index: PublishedIndex | null }) {
  const { state, retry } = usePublishedStandings(year);
  const season = index ? findSeason(index, year) : null;
  const standings = state.status === "ready" ? state.standings : null;
  return (
    <div>
      <PageHeader
        title={`${year} Season Standings`}
        description={standings ? `${describeRounds(standings, season)} ${SOURCE_NOTE}` : SOURCE_NOTE}
      />
      {index ? <SeasonLinks index={index} current={year} /> : null}
      {state.status === "loading" ? <LoadingState label="Loading standings" /> : null}
      {state.status === "failed" ? (
        <LoadFailure failure={state.failure} onRetry={retry} />
      ) : null}
      {state.status === "ready" && !state.standings ? (
        <EmptyState
          title={`No standings are published for ${year}`}
          detail="Standings are published once a season's first round has been run. Nothing is worked out from session results in their place."
        />
      ) : null}
      {standings ? <Tables standings={standings} season={season} /> : null}
    </div>
  );
}

function describeRounds(standings: Standings, season: IndexSeason | null): string {
  const rounds = standingsRounds(standings, season);
  return rounds.agree
    ? `${roundLabel(rounds.drivers)}.`
    : `The two tables are a round apart at the moment: drivers after round ${rounds.drivers.round}, constructors after round ${rounds.constructors.round}.`;
}

function Tables({ standings, season }: { standings: Standings; season: IndexSeason | null }) {
  const rounds = standingsRounds(standings, season);
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.6fr)]">
      <section aria-labelledby="driver-standings">
        <TableHeading id="driver-standings" title="Drivers" round={rounds.drivers} />
        <DataTable
          rows={[...standings.drivers]}
          emptyText="The published standings list no drivers."
          columns={[
            { key: "pos", header: "Pos", align: "right", render: (row) => <Position value={row.position} /> },
            {
              key: "driver",
              header: "Driver",
              render: (row) => (
                <span className="inline-flex items-baseline gap-3">
                  <span className="font-mono font-semibold text-white">{row.driver_code ?? "--"}</span>
                  <span className="text-slate-400">{driverName(row)}</span>
                </span>
              )
            },
            { key: "team", header: "Team", render: (row) => row.constructors.join(" / ") || "--" },
            { key: "wins", header: "Wins", align: "right", render: (row) => row.wins },
            {
              key: "points",
              header: "Pts",
              align: "right",
              render: (row) => <span className="font-mono font-black text-white">{row.points}</span>
            }
          ]}
        />
      </section>
      <section aria-labelledby="constructor-standings">
        <TableHeading id="constructor-standings" title="Constructors" round={rounds.constructors} />
        <Constructors rows={standings.constructors} />
      </section>
    </div>
  );
}

/** Each table says which round it is after, because the two can differ. */
function TableHeading({ id, title, round }: { id: string; title: string; round: StandingsRound }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h2 id={id} className="font-bold text-white">
        {title}
      </h2>
      <p className="text-xs text-slate-500">{roundLabel(round)}</p>
    </div>
  );
}

function Constructors({ rows }: { rows: ReadonlyArray<ConstructorStanding> }) {
  if (rows.length === 0) {
    return <div className="surface p-6 text-center text-sm text-slate-500">The published standings list no constructors.</div>;
  }
  return (
    <div className="surface overflow-hidden">
      {rows.map((row, index) => (
        <div
          key={row.constructor_id ?? `${row.name}-${index}`}
          className="grid grid-cols-[32px_1fr_auto_auto] items-center gap-3 border-b border-line/60 px-4 py-3 last:border-0"
        >
          <Position value={row.position} />
          <span className="truncate text-sm font-semibold text-slate-200">{row.name}</span>
          <span className="text-xs text-slate-500">
            {row.wins} {row.wins === 1 ? "win" : "wins"}
          </span>
          <span className="w-12 text-right font-mono text-sm font-black text-white">{row.points}</span>
        </div>
      ))}
    </div>
  );
}

/** The published position. A driver Jolpica has not classified has none, and is not given one here. */
function Position({ value }: { value: number | null }) {
  return <span className="font-mono font-black">{value ?? "--"}</span>;
}

function SeasonLinks({ index, current }: { index: PublishedIndex; current: number | null }) {
  const years = seasonOverviews(index).map((season) => season.year);
  if (years.length < 2 && years[0] === current) {
    return null;
  }
  return (
    <nav className="mb-5 flex flex-wrap items-center gap-2" aria-label="Season">
      {years.map((year) => (
        <Link
          key={year}
          href={standingsHref(year)}
          aria-current={year === current ? "page" : undefined}
          className={clsx(
            "rounded border px-3 py-1.5 text-sm font-semibold",
            year === current ? "border-redline/60 bg-redline/15 text-white" : "border-line text-slate-300 hover:border-slate-500"
          )}
        >
          {year}
        </Link>
      ))}
    </nav>
  );
}
