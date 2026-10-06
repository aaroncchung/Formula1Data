import { PageHeader } from "@/components/dashboard/PageHeader";
import { compactDate } from "@/lib/format";
import type { SessionEntry } from "@/lib/published/lookup";

/**
 * Everything here comes from the index entry, so the header reads the same
 * whether the session turned out to be published, unpublished or broken, and
 * the round is the one the calendar gives the meeting today.
 */
export function SessionHeader({ entry, actions }: { entry: SessionEntry; actions?: React.ReactNode }) {
  const { meeting, session } = entry;
  const place = [meeting.location, meeting.country].filter(Boolean).join(", ");
  const date = compactDate(session.start_time_utc ?? meeting.date);
  return (
    <PageHeader
      eyebrow={`${entry.year} Round ${meeting.round}`}
      title={`${meeting.name} - ${session.name}`}
      description={place ? `${date} · ${place}` : date}
      actions={actions}
    />
  );
}
