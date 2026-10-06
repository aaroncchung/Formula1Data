"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { MeetingWeekend } from "@/components/calendar/MeetingWeekend";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { SEASONS_PATH, meetingHref, roundParam, yearParam } from "@/lib/routes";

/**
 * `/meeting?year=2026&round=8`: one race weekend and its sessions.
 *
 * The index gives a meeting no key of its own, so it is named by where the
 * calendar has it. That is looked up when the page opens and is good for a
 * link made from today's calendar; a session, which does have a key, is
 * always linked by it.
 */
export default function MeetingPage() {
  return (
    // See app/season/page.tsx for why the query is read inside a Suspense
    // boundary.
    <Suspense fallback={<LoadingState label="Loading the calendar" />}>
      <MeetingFromQuery />
    </Suspense>
  );
}

function MeetingFromQuery() {
  const query = useSearchParams();
  const year = yearParam(query);
  const round = roundParam(query);
  if (year.status !== "ok" || round.status !== "ok") {
    return (
      <div>
        <EmptyState
          title={year.status === "absent" && round.status === "absent" ? "No meeting selected" : "Not a meeting"}
          detail={`A meeting is named by its year and round, for example ${meetingHref(2026, 8)}.`}
        />
        <div className="mt-4 text-center">
          <Link className="text-sm font-semibold text-slate-200 underline-offset-4 hover:underline" href={SEASONS_PATH}>
            See every season
          </Link>
        </div>
      </div>
    );
  }
  return <MeetingWeekend year={year.value} round={round.value} />;
}
