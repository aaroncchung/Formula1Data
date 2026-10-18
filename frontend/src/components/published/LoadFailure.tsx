import { ErrorState } from "@/components/dashboard/ErrorState";
import { failureDetail, failureTitle } from "@/components/published/failure-copy";
import { RetryButton } from "@/components/published/RetryButton";
import type { PublishedFailure } from "@/lib/published/errors";

/**
 * A read that failed, said plainly, with a way to ask again. The title is the
 * reader's own word for what went wrong, so an outage, a calendar in another
 * format and a missing calendar each look like what they are, and none of
 * them looks like a season with nothing in it.
 */
export function LoadFailure({ failure, onRetry }: { failure: PublishedFailure; onRetry: () => void }) {
  return (
    <div className="space-y-3">
      <ErrorState title={failureTitle(failure)} detail={failureDetail(failure)} />
      <RetryButton onClick={onRetry} />
    </div>
  );
}
