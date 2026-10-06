"use client";

import { Suspense } from "react";

import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { SeasonStandings } from "@/components/standings/SeasonStandings";

/** `/standings?year=2026`, or the current season when no year is given. */
export default function StandingsPage() {
  return (
    // See app/season/page.tsx for why the query is read inside a Suspense
    // boundary.
    <Suspense
      fallback={
        <div>
          <PageHeader title="Season Standings" />
          <LoadingState label="Loading standings" />
        </div>
      }
    >
      <SeasonStandings />
    </Suspense>
  );
}
