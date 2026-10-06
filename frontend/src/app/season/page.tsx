"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { SeasonCalendar } from "@/components/calendar/SeasonCalendar";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { SEASONS_PATH, seasonHref, yearParam } from "@/lib/routes";

/**
 * `/season?year=2026`.
 *
 * The season is named in the query string and not in the path, as a session
 * is on `/session`: a static export can only write a file for a path it knows
 * when it is built, and the seasons this page shows are whichever the
 * published calendar lists when it is opened.
 */
export default function SeasonPage() {
  return (
    // The query string does not exist while the shell is exported, and Next
    // refuses to export a page that reads it outside a Suspense boundary. The
    // exported HTML is this fallback; the season renders in the browser.
    <Suspense fallback={<LoadingState label="Loading the calendar" />}>
      <SeasonFromQuery />
    </Suspense>
  );
}

function SeasonFromQuery() {
  const year = yearParam(useSearchParams());
  if (year.status !== "ok") {
    return (
      <div>
        <EmptyState
          title={year.status === "absent" ? "No season selected" : "Not a season"}
          detail={`A season is named by its year, for example ${seasonHref(2026)}.`}
        />
        <div className="mt-4 text-center">
          <Link className="text-sm font-semibold text-slate-200 underline-offset-4 hover:underline" href={SEASONS_PATH}>
            See every season
          </Link>
        </div>
      </div>
    );
  }
  return <SeasonCalendar year={year.value} />;
}
