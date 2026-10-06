"use client";

import Link from "next/link";

import { CalendarPage } from "@/components/calendar/CalendarPage";
import { SessionChip, SessionStateBadge, SessionStateLegend } from "@/components/calendar/SessionState";
import { useNow } from "@/components/calendar/useNow";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { findSeason, seasonOverviews, sessionAvailability, unscheduledSessions } from "@/lib/calendar";
import type { PublishedSession } from "@/lib/calendar";
import { calendarDay, sessionStart } from "@/lib/format";
import type { IndexMeeting, PublishedIndex } from "@/lib/published/types";
import { meetingHref, seasonHref, sessionHref, standingsHref, SEASONS_PATH } from "@/lib/routes";

export function SeasonCalendar({ year }: { year: number }) {
  return (
    <CalendarPage title={`${year} Season`}>{(index) => <Season index={index} year={year} />}</CalendarPage>
  );
}

function Season({ index, year }: { index: PublishedIndex; year: number }) {
  const now = useNow();
  const season = findSeason(index, year);
  const unscheduled = unscheduledSessions(index, year);
  const overview = seasonOverviews(index).find((item) => item.year === year);

  if (!overview) {
    return (
      <div>
        <PageHeader title={`${year} Season`} />
        <EmptyState
          title={`There is no ${year} season in the published calendar`}
          detail="The calendar was read, and it does not list this year."
        />
        <OtherSeasons index={index} />
      </div>
    );
  }

  const meetings = [...(season?.meetings ?? [])].sort((left, right) => left.round - right.round);
  return (
    <div>
      <PageHeader
        eyebrow="Season"
        title={`${year} Season`}
        description={`${overview.meetingCount} ${overview.meetingCount === 1 ? "meeting" : "meetings"} in the calendar · ${overview.publishedCount} of ${overview.sessionCount + overview.unscheduledCount} sessions published${overview.partialCount > 0 ? `, ${overview.partialCount} with partial data` : ""}.`}
        actions={
          <>
            <Link className="rounded border border-line px-4 py-2 text-sm font-bold text-slate-200" href={standingsHref(year)}>
              Standings
            </Link>
            <Link className="rounded border border-line px-4 py-2 text-sm font-bold text-slate-200" href={SEASONS_PATH}>
              All seasons
            </Link>
          </>
        }
      />
      {meetings.length === 0 ? (
        <EmptyState
          title={`The ${year} calendar lists no meetings yet`}
          detail="The season is in the published calendar, and no race weekend has been added to it."
        />
      ) : (
        <>
          <div className="mb-4">
            <SessionStateLegend />
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            {meetings.map((meeting) => (
              <MeetingCard key={meeting.round} year={year} meeting={meeting} now={now} />
            ))}
          </div>
        </>
      )}
      {unscheduled.length > 0 ? <Unscheduled sessions={unscheduled} /> : null}
    </div>
  );
}

function MeetingCard({ year, meeting, now }: { year: number; meeting: IndexMeeting; now: number }) {
  const place = [meeting.location, meeting.country].filter(Boolean).join(", ");
  const sprint = meeting.format?.startsWith("sprint") ?? false;
  return (
    <article className="surface p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
            Round {meeting.round}
            {sprint ? <span className="text-amber"> · Sprint weekend</span> : null}
          </div>
          <h2 className="mt-2 text-xl font-black text-white">
            <Link href={meetingHref(year, meeting.round)} className="transition hover:text-redline">
              {meeting.name}
            </Link>
          </h2>
          {place ? <div className="mt-1 text-sm text-slate-400">{place}</div> : null}
        </div>
        <div className="shrink-0 text-right text-sm text-slate-400">{calendarDay(meeting.date)}</div>
      </div>
      {/* The sessions are links of their own, so the card is not one: a link
          inside a link is not valid, and each session goes somewhere else. */}
      <ul className="mt-4 flex flex-wrap gap-2" aria-label={`Sessions of the ${meeting.name}`}>
        {meeting.sessions.map((session) => (
          <li key={session.type}>
            <SessionChip session={session} state={sessionAvailability(session, now)} />
          </li>
        ))}
      </ul>
    </article>
  );
}

/**
 * Published sessions the calendar has no entry for, which happens while the
 * calendar is being changed. They are published, so they are shown and can be
 * opened; only their place in the season is unknown.
 */
function Unscheduled({ sessions }: { sessions: PublishedSession[] }) {
  return (
    <section className="mt-8" aria-labelledby="unscheduled-heading">
      <h2 id="unscheduled-heading" className="text-base font-bold text-white">
        Published sessions the calendar does not list
      </h2>
      <p className="mt-1 max-w-3xl text-sm text-slate-400">
        These sessions have data, and the current calendar has no entry for them. This happens while a race is being
        moved or renamed.
      </p>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {sessions.map((session) => (
          <li key={session.key}>
            <Link
              href={sessionHref(session.key)}
              className="surface block p-4 transition hover:-translate-y-0.5 hover:border-redline/50"
            >
              <div className="font-bold text-white">
                {session.meetingName} · {session.name}
              </div>
              <div className="mt-1 text-xs text-slate-500">{sessionStart(session.startTimeUtc)}</div>
              <div className="mt-3">
                <SessionStateBadge state={session.complete ? "complete" : "partial"} />
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The seasons the calendar does have, for a reader who asked for one it does not. */
function OtherSeasons({ index }: { index: PublishedIndex }) {
  const seasons = seasonOverviews(index);
  if (seasons.length === 0) {
    return null;
  }
  return (
    <div className="mt-5 flex flex-wrap items-center gap-2 text-sm text-slate-400">
      <span>Seasons in the calendar:</span>
      {seasons.map((season) => (
        <Link
          key={season.year}
          href={seasonHref(season.year)}
          className="rounded border border-line px-3 py-1 font-semibold text-slate-200 hover:border-redline/60"
        >
          {season.year}
        </Link>
      ))}
    </div>
  );
}
