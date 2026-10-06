"use client";

import Link from "next/link";

import { CalendarPage } from "@/components/calendar/CalendarPage";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { seasonOverviews } from "@/lib/calendar";
import type { SeasonOverview } from "@/lib/calendar";
import type { PublishedIndex } from "@/lib/published/types";
import { seasonHref } from "@/lib/routes";

const DESCRIPTION = "Every season in the published calendar, and how much of each has data.";

export function SeasonsList() {
  return (
    <CalendarPage title="Seasons" description={DESCRIPTION}>
      {(index) => <Seasons index={index} />}
    </CalendarPage>
  );
}

function Seasons({ index }: { index: PublishedIndex }) {
  const seasons = seasonOverviews(index);
  return (
    <div>
      <PageHeader title="Seasons" description={DESCRIPTION} />
      {seasons.length === 0 ? (
        <EmptyState
          title="The published calendar has no seasons"
          detail="The calendar was read, and it lists no season yet. Seasons appear here as they are published, without a new version of the site."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {seasons.map((season) => (
            <SeasonCard key={season.year} season={season} />
          ))}
        </div>
      )}
    </div>
  );
}

function SeasonCard({ season }: { season: SeasonOverview }) {
  return (
    <Link
      href={seasonHref(season.year)}
      className="surface group p-5 transition hover:-translate-y-0.5 hover:border-redline/50"
    >
      <div className="text-3xl font-black text-white transition group-hover:text-redline">{season.year}</div>
      <div className="mt-3 text-sm text-slate-400">
        {season.meetingCount} {season.meetingCount === 1 ? "meeting" : "meetings"} in the calendar
      </div>
      <div className="mt-1 text-sm text-slate-400">
        <span className="font-semibold text-slate-200">{season.publishedCount}</span>{" "}
        {season.publishedCount === 1 ? "session" : "sessions"} published
      </div>
      {season.partialCount > 0 ? (
        <div className="mt-3 text-xs font-bold uppercase text-amber">{season.partialCount} with partial data</div>
      ) : null}
    </Link>
  );
}
