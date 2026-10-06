"use client";

import clsx from "clsx";
import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";

import { CalendarPage } from "@/components/calendar/CalendarPage";
import { SessionStateBadge } from "@/components/calendar/SessionState";
import { useNow } from "@/components/calendar/useNow";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { findMeeting, sessionAvailability } from "@/lib/calendar";
import type { SessionAvailability } from "@/lib/calendar";
import { calendarDay, sessionStart } from "@/lib/format";
import type { IndexMeeting, IndexSession, PublishedIndex } from "@/lib/published/types";
import { meetingHref, seasonHref, sessionHref } from "@/lib/routes";

export function MeetingWeekend({ year, round }: { year: number; round: number }) {
  return (
    <CalendarPage title={`${year} Round ${round}`}>
      {(index) => <Meeting index={index} year={year} round={round} />}
    </CalendarPage>
  );
}

function Meeting({ index, year, round }: { index: PublishedIndex; year: number; round: number }) {
  const now = useNow();
  // Looked up in the calendar as it is now. The round in the address is where
  // the meeting sat when the link was made; after a calendar change the same
  // address is a different weekend, and this shows whichever it is today.
  const lookup = findMeeting(index, year, round);
  if (!lookup.found) {
    return (
      <div>
        <PageHeader title={`${year} Round ${round}`} />
        <EmptyState
          title="Meeting not found"
          detail={
            lookup.missing === "year"
              ? `There is no ${year} season in the published calendar.`
              : `The ${year} calendar has no round ${round}. Rounds are renumbered when the calendar changes.`
          }
        />
        {lookup.missing === "round" ? (
          <div className="mt-4 text-center">
            <Link className="text-sm font-semibold text-slate-200 underline-offset-4 hover:underline" href={seasonHref(year)}>
              See the {year} calendar
            </Link>
          </div>
        ) : null}
      </div>
    );
  }

  const { meeting, previous, next } = lookup;
  const place = [meeting.location, meeting.country].filter(Boolean).join(", ");
  const sprint = meeting.format?.startsWith("sprint") ?? false;
  const facts = [calendarDay(meeting.date), place, sprint ? "Sprint weekend" : null].filter(Boolean).join(" · ");
  const published = meeting.sessions.filter((session) => session.session_key !== null).length;
  return (
    <div>
      <PageHeader
        eyebrow={`${year} Round ${meeting.round}`}
        title={meeting.name}
        description={meeting.official_name ? `${meeting.official_name}. ${facts}` : facts}
        actions={
          <>
            <NeighbourLink year={year} meeting={previous} direction="previous" />
            <Link className="rounded border border-line px-4 py-2 text-sm font-bold text-slate-200" href={seasonHref(year)}>
              {year} calendar
            </Link>
            <NeighbourLink year={year} meeting={next} direction="next" />
          </>
        }
      />
      <p className="mb-4 text-sm text-slate-400">
        {published === 0
          ? "None of this weekend's sessions is published yet."
          : `${published} of ${meeting.sessions.length} sessions published.`}
      </p>
      {meeting.sessions.length === 0 ? (
        <EmptyState title="No sessions listed" detail="The calendar has this meeting, and no sessions for it yet." />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          {meeting.sessions.map((session) => (
            <li key={session.type}>
              <SessionCard session={session} state={sessionAvailability(session, now)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SessionCard({ session, state }: { session: IndexSession; state: SessionAvailability }) {
  const body = (
    <>
      <div className="text-3xl font-black text-white">{session.type}</div>
      <div className="mt-2 text-sm text-slate-300">{session.name}</div>
      <div className="mt-1 text-xs text-slate-500">{sessionStart(session.start_time_utc)}</div>
      <div className="mt-4">
        <SessionStateBadge state={state} />
      </div>
    </>
  );
  // Only a published session has a dashboard, and it is reached by its key.
  // The others are shown as what they are and lead nowhere.
  if (session.session_key === null) {
    return (
      <div className={clsx("h-full rounded-lg border border-line/60 bg-panel/50 p-5", state === "scheduled" && "border-dashed")}>
        {body}
        <div className="mt-3 text-xs text-slate-500">
          {state === "scheduled" ? "Not run yet." : "No data is published for this session."}
        </div>
      </div>
    );
  }
  return (
    <Link
      href={sessionHref(session.session_key)}
      className="surface group block h-full p-5 transition hover:-translate-y-0.5 hover:border-redline/50"
    >
      {body}
      <div className="mt-3 text-xs font-semibold text-slate-300 transition group-hover:text-white">Open session →</div>
    </Link>
  );
}

function NeighbourLink({
  year,
  meeting,
  direction
}: {
  year: number;
  meeting: IndexMeeting | null;
  direction: "previous" | "next";
}) {
  if (!meeting) {
    return null;
  }
  return (
    <Link
      className="inline-flex items-center gap-2 rounded border border-line px-3 py-2 text-sm font-bold text-slate-200"
      href={meetingHref(year, meeting.round)}
      title={`${direction === "previous" ? "Previous" : "Next"} meeting: ${meeting.name}`}
    >
      {direction === "previous" ? <ArrowLeft size={15} aria-hidden="true" /> : null}
      <span className="max-w-[12rem] truncate">{meeting.name}</span>
      {direction === "next" ? <ArrowRight size={15} aria-hidden="true" /> : null}
    </Link>
  );
}
