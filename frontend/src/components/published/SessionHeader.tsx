import Link from "next/link";

import { PageHeader } from "@/components/dashboard/PageHeader";
import { sessionWhen } from "@/lib/format";
import type { SessionHeading } from "@/lib/published/lookup";
import { meetingHref } from "@/lib/routes";

/**
 * The heading of a session page. For a session the calendar places it comes
 * from the index entry, so it reads the same whether the session turned out
 * to be published, unpublished or broken, and the round is the one the
 * calendar gives the meeting today. A session the calendar has no entry for
 * has no round, and the header says which of the two reasons applies.
 */
export function SessionHeader({ heading, actions }: { heading: SessionHeading; actions?: React.ReactNode }) {
  const place = [heading.location, heading.country].filter(Boolean).join(", ");
  const date = sessionWhen(heading.startTimeUtc);
  return (
    <PageHeader
      eyebrow={eyebrow(heading)}
      title={`${heading.meetingName} - ${heading.sessionName}`}
      description={place ? `${date} · ${place}` : date}
      actions={
        <>
          <WeekendLink heading={heading} />
          {actions}
        </>
      }
    />
  );
}

/**
 * The way from a session to its weekend. Only for a session the calendar
 * places: one it has no entry for has no meeting page to go to. The link is
 * by the meeting's key where there is one, like every link to a session.
 */
function WeekendLink({ heading }: { heading: SessionHeading }) {
  if (heading.placement !== "calendar" || heading.round === null) {
    return null;
  }
  return (
    <Link
      className="rounded border border-line px-4 py-2 text-sm font-bold text-slate-200"
      href={meetingHref(heading.year, { meeting_key: heading.meetingKey, round: heading.round })}
    >
      Race weekend
    </Link>
  );
}

function eyebrow(heading: SessionHeading): string {
  if (heading.round !== null) {
    return `${heading.year} Round ${heading.round}`;
  }
  // Published, and the current calendar has no entry for it. A session the
  // index says nothing about gets the year alone: there is nothing to add.
  return heading.placement === "unscheduled" ? `${heading.year} · Not in the current calendar` : String(heading.year);
}
