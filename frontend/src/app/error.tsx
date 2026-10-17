"use client";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { drawFailureDetail, drawFailureTitle } from "@/components/published/failure-copy";
import { RetryButton } from "@/components/published/RetryButton";

/**
 * A page that threw while it was drawn, where nothing nearer caught it. This
 * stands in for the page alone: the navigation and the session picker are in
 * the root layout, outside it, and stay. `reset` draws the page again, which
 * reads again whatever it reads.
 */
export default function PageError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="space-y-3">
      <ErrorState title={drawFailureTitle()} detail={drawFailureDetail(error)} />
      <RetryButton onClick={reset} />
    </div>
  );
}
