"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PublishedSession } from "@/components/published/PublishedSession";
import { parseSessionAddress } from "@/lib/published/lookup";

/**
 * `/session?key=11315`, or `/session?year=2026&round=8&session=R`.
 *
 * The session is named in the query string and not in the path. A static
 * export can only write a file for a path it knows when it is built, and the
 * sessions this page shows are the ones published after that.
 *
 * The key is F1's own and stays with the session; it is what the site's links
 * carry. Year, round and type are a way in for a person: the round is looked
 * up in the calendar as it stands today.
 */
export default function SessionPage() {
  return (
    // The query string does not exist while the shell is exported, and Next
    // refuses to export a page that reads it outside a Suspense boundary. The
    // exported HTML is this fallback; the session renders in the browser.
    <Suspense fallback={<LoadingState label="Loading session" />}>
      <SessionFromQuery />
    </Suspense>
  );
}

function SessionFromQuery() {
  const address = parseSessionAddress(useSearchParams());
  if (!address) {
    return (
      <EmptyState
        title="No session selected"
        detail="A session is named by its key, for example /session?key=11315, or by its year, round and session type, for example /session?year=2026&round=8&session=R."
      />
    );
  }
  return <PublishedSession address={address} />;
}
