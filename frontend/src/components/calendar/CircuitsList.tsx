"use client";

import { MapPin } from "lucide-react";
import Link from "next/link";

import { CalendarPage } from "@/components/calendar/CalendarPage";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { circuits } from "@/lib/calendar";
import type { Circuit, CircuitGuide } from "@/lib/calendar";
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
  const guide = circuits(index);
  const count = guide.circuits.length;
  return (
    <div>
      <PageHeader
        title="Circuits"
        description={`${count} ${count === 1 ? "circuit" : "circuits"} across the published calendar, each with the meetings held there.`}
      />
      {count === 0 && guide.unidentified.length === 0 ? (
        <EmptyState
          title="The published calendar has no meetings"
          detail="The calendar was read, and it lists no race weekend yet, so there is no circuit to show."
        />
      ) : null}
      {count > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {guide.circuits.map((circuit) => (
            <CircuitCard key={circuit.key} circuit={circuit} />
          ))}
        </div>
      ) : null}
      <Unidentified meetings={guide.unidentified} />
    </div>
  );
}

function CircuitCard({ circuit }: { circuit: Circuit }) {
  const latest = circuit.meetings[0];
  if (!latest) {
    return null;
  }
  const years = [...new Set(circuit.meetings.map((item) => item.year))];
  // F1's name for a circuit is often the town it is in, and then the town is not said twice.
  const where = [circuit.location === circuit.name ? null : circuit.location, circuit.country].filter(Boolean).join(", ");
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
          <div className="font-mono text-sm font-bold text-white">{circuit.publishedCount}</div>
          <div className="text-[10px] uppercase tracking-wider text-slate-600">
            {circuit.publishedCount === 1 ? "session published" : "sessions published"}
          </div>
        </div>
      </div>
      <div className="mt-4 text-xl font-black text-white transition group-hover:text-redline">{circuit.name}</div>
      <div className="mt-1 text-sm text-slate-400">{[latest.meeting.name, where].filter(Boolean).join(" · ")}</div>
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

/**
 * The meetings the calendar names no circuit for. They are listed, and not
 * guessed onto a circuit by the name of their town: the calendar says which
 * circuit a meeting is at once one of its sessions is published.
 */
function Unidentified({ meetings }: { meetings: CircuitGuide["unidentified"] }) {
  if (meetings.length === 0) {
    return null;
  }
  return (
    <section className="mt-8" aria-labelledby="unidentified-heading">
      <h2 id="unidentified-heading" className="text-base font-bold text-white">
        Meetings whose circuit the calendar does not name yet
      </h2>
      <p className="mt-1 max-w-3xl text-sm text-slate-400">
        The calendar names a meeting&apos;s circuit once one of its sessions is published. None of these has one
        published.
      </p>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {meetings.map(({ year, meeting }) => (
          <li key={`${year}/${meeting.round}`}>
            <Link
              href={meetingHref(year, meeting)}
              className="block rounded-lg border border-dashed border-line/70 p-4 transition hover:border-redline/50"
            >
              <div className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
                {year} · Round {meeting.round}
              </div>
              <div className="mt-1 font-bold text-white">{meeting.name}</div>
              <div className="mt-1 text-sm text-slate-400">
                {[meeting.location, meeting.country].filter(Boolean).join(", ") || "Place not given"}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
