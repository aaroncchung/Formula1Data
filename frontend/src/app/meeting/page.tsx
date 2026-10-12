"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { MeetingWeekend } from "@/components/calendar/MeetingWeekend";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { SEASONS_PATH, meetingChoice } from "@/lib/routes";

/**
 * `/meeting?key=1288` or `/meeting?year=2026&round=8`: one race weekend and
 * its sessions.
 *
 * The site links a meeting by F1's key for it, which the index has once one
 * of the meeting's sessions is published and which does not move with the
 * calendar. A meeting without one yet is linked by where the calendar has it,
 * which is looked up when the page opens and is good for a link made from
 * today's calendar.
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
  const choice = meetingChoice(useSearchParams());
  if (choice.kind !== "named") {
    return (
      <div>
        <EmptyState
          title={choice.kind === "none" ? "No meeting selected" : "Not a meeting"}
          detail="A meeting is named by its key, or by its year and round: /meeting?key=1288 or /meeting?year=2026&round=8."
        />
        <div className="mt-4 text-center">
          <Link className="text-sm font-semibold text-slate-200 underline-offset-4 hover:underline" href={SEASONS_PATH}>
            See every season
          </Link>
        </div>
      </div>
    );
  }
  return <MeetingWeekend address={choice.address} />;
}
