"use client";

import { LoadFailure } from "@/components/calendar/LoadFailure";
import { usePublishedIndex } from "@/components/calendar/usePublishedIndex";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import type { PublishedIndex } from "@/lib/published/types";

type CalendarPageProps = {
  /** The heading while there is no calendar to take a better one from. */
  title: string;
  description?: string;
  /** The page once the calendar is read. It renders its own heading. */
  children: (index: PublishedIndex) => React.ReactNode;
};

/**
 * A page made from the published calendar. The calendar is read in the
 * browser, so what the page shows is what is published now and not what was
 * in the repository when the site was built (AR-07).
 *
 * The page proper is only rendered from a calendar that was read. Until then
 * the reader sees that it is loading, or exactly why it could not be read; an
 * outage never reaches the code that would draw it as an empty season.
 */
export function CalendarPage({ title, description, children }: CalendarPageProps) {
  const { state, retry } = usePublishedIndex();
  if (state.status === "ready") {
    return <>{children(state.index)}</>;
  }
  return (
    <div>
      <PageHeader title={title} description={description} />
      {state.status === "loading" ? (
        <LoadingState label="Loading the calendar" />
      ) : (
        <LoadFailure failure={state.failure} onRetry={retry} />
      )}
    </div>
  );
}
