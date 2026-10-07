"use client";

import { MapPin } from "lucide-react";
import Link from "next/link";

import { CalendarPage } from "@/components/calendar/CalendarPage";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { venues } from "@/lib/calendar";
import type { Venue } from "@/lib/calendar";
import type { PublishedIndex } from "@/lib/published/types";
import { meetingHref } from "@/lib/routes";

export function CircuitsList() {
  return (
    <CalendarPage title="Circuits" description="Where the published calendar goes.">
      {(index) => <Circuits index={index} />}
    </CalendarPage>
  );
}

function Circuits({ index }: { index: PublishedIndex }) {
  const places = venues(index);
  return (
    <div>
      <PageHeader
        title="Circuits"
        description={`${places.length} ${places.length === 1 ? "venue" : "venues"} across the published calendar, each with the meetings held there.`}
      />
      {places.length === 0 ? (
        <EmptyState
          title="The published calendar has no meetings"
          detail="The calendar was read, and it lists no race weekend yet, so there is no venue to show."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {places.map((venue) => (
            <VenueCard key={venue.id} venue={venue} />
          ))}
        </div>
      )}
    </div>
  );
}

function VenueCard({ venue }: { venue: Venue }) {
  const latest = venue.meetings[0];
  if (!latest) {
    return null;
  }
  const years = [...new Set(venue.meetings.map((item) => item.year))];
  return (
    <Link
      href={meetingHref(latest.year, latest.meeting)}
      className="surface group block p-5 transition hover:-translate-y-0.5 hover:border-redline/50"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-md border border-line bg-carbon/50 text-redline">
          <MapPin size={18} aria-hidden="true" />
        </div>
        <div className="text-right">
          <div className="font-mono text-sm font-bold text-white">{venue.publishedCount}</div>
          <div className="text-[10px] uppercase tracking-wider text-slate-600">
            {venue.publishedCount === 1 ? "session published" : "sessions published"}
          </div>
        </div>
      </div>
      <div className="mt-4 text-xl font-black text-white transition group-hover:text-redline">{venue.place}</div>
      <div className="mt-1 text-sm text-slate-400">
        {[latest.meeting.name, venue.country].filter(Boolean).join(" · ")}
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {years.slice(0, 6).map((year) => (
          <span key={year} className="rounded border border-line/70 bg-carbon/40 px-2 py-1 font-mono text-[11px] text-slate-400">
            {year}
          </span>
        ))}
        {years.length > 6 ? <span className="px-2 py-1 text-[11px] text-slate-600">+{years.length - 6}</span> : null}
      </div>
    </Link>
  );
}
