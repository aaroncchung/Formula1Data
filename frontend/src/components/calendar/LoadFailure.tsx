import { ErrorState } from "@/components/dashboard/ErrorState";
import { failureDetail, failureTitle } from "@/components/published/failure-copy";
import { RetryButton } from "@/components/published/RetryButton";
import type { PublishedFailure } from "@/lib/published/errors";

type LoadFailureProps = {
  failure: PublishedFailure;
  onRetry: () => void;
  /** For a read whose failure needs its own words; the reader's title otherwise. */
  title?: string;
};

/**
 * A read that failed, said plainly, with a way to ask again. The title is the
 * reader's own word for what went wrong, so an outage, a calendar in another
 * format and a missing calendar each look like what they are, and none of
 * them looks like a season with nothing in it.
 */
export function LoadFailure({ failure, onRetry, title }: LoadFailureProps) {
  return (
    <div className="space-y-3">
      <ErrorState title={title ?? failureTitle(failure)} detail={failureDetail(failure)} />
      <RetryButton onClick={onRetry} />
    </div>
  );
}
