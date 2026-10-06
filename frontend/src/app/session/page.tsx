"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { EmptyState } from "@/components/dashboard/EmptyState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PublishedSession } from "@/components/published/PublishedSession";
import { parseSessionRoute } from "@/lib/published/lookup";

/**
 * `/session?year=2026&round=8&session=R`.
 *
 * The session is named in the query string and not in the path. A static
 * export can only write a file for a path it knows when it is built, and the
 * sessions this page shows are the ones published after that.
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
  const route = parseSessionRoute(useSearchParams());
  if (!route) {
    return (
      <EmptyState
        title="No session selected"
        detail="A session is named by its year, round and session type, for example /session?year=2026&round=8&session=R."
      />
    );
  }
  return <PublishedSession year={route.year} round={route.round} sessionType={route.sessionType} />;
}
