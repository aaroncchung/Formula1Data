import { PageHeader } from "@/components/dashboard/PageHeader";
import { compactDate } from "@/lib/format";
import type { SessionHeading } from "@/lib/published/lookup";

/**
 * The heading of a session page. For a session the calendar places it comes
 * from the index entry, so it reads the same whether the session turned out
 * to be published, unpublished or broken, and the round is the one the
 * calendar gives the meeting today. A session the calendar has no entry for
 * has no round, and the header says which of the two reasons applies.
 */
export function SessionHeader({ heading, actions }: { heading: SessionHeading; actions?: React.ReactNode }) {
  const place = [heading.location, heading.country].filter(Boolean).join(", ");
  const date = compactDate(heading.startTimeUtc);
  return (
    <PageHeader
      eyebrow={eyebrow(heading)}
      title={`${heading.meetingName} - ${heading.sessionName}`}
      description={place ? `${date} · ${place}` : date}
      actions={actions}
    />
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
