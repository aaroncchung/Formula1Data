import type { PublishedFailure } from "@/lib/published/errors";

/**
 * The heading for each way a read can fail. The reader's own message goes
 * underneath as the detail, so each case names itself here and explains
 * itself there, and no two of them look alike on the page.
 */
export function failureTitle(failure: PublishedFailure): string {
  switch (failure.code) {
    case "not_configured":
      return "No data source is configured";
    case "unavailable":
      return "Published data could not be reached";
    case "index_missing":
      return "No published data was found";
    case "invalid_index":
      return "The published calendar is invalid";
    case "not_published":
      return "This session is not published";
    case "invalid_pointer":
      return "This session's publication record is invalid";
    case "invalid_manifest":
      return "This session's file list is invalid";
    case "format_mismatch":
      return failure.details.site === "newer"
        ? "This site is newer than the published data"
        : "This site is older than the published data";
    case "generation_gone":
      return "This session's published files are missing";
    case "not_in_manifest":
      return "Not part of this session's published data";
    case "invalid_artifact":
      return "This part of the session's data is invalid";
    case "invalid_standings":
      return "The published standings are invalid";
    case "unknown":
      return "Something went wrong";
  }
}

/** What the reader said, plus what the person looking at the page can do about it. */
export function failureDetail(failure: PublishedFailure): string {
  switch (failure.code) {
    case "not_configured":
      return `${failure.message} Set NEXT_PUBLIC_PUBLISHED_DATA_BASE_URL when the site is built.`;
    case "format_mismatch":
      return failure.details.site === "newer"
        ? `${failure.message} The data has not been published in this site's format yet.`
        : `${failure.message} Reload the page to get the current site.`;
    default:
      return failure.message;
  }
}

/**
 * The heading for a part of a page whose data was read and could not be
 * drawn: a fault in the site, not a state of the data. `name` is what the
 * part shows, as it reads in a sentence; without one it is the whole page.
 */
export function drawFailureTitle(name?: string): string {
  return name ? `The ${name} could not be shown` : "This page could not be shown";
}

/** What was thrown while drawing. */
export function drawFailureDetail(error: unknown): string {
  const message = error instanceof Error && error.message ? error.message : String(error);
  return `It failed while being drawn: ${message.replace(/\.$/, "")}.`;
}
