/**
 * One request for several callers that ask at the same moment.
 *
 * Every page reads the calendar, and so does the picker in the bar above it,
 * in the same tick when the page loads. Each asking on its own is two
 * requests for one file. The callers share the request only while it is in
 * flight: once it settles the next call asks again, so nothing is kept here
 * and how long an answer may be reused stays the HTTP cache's decision, on
 * the Worker's terms (30 seconds for the index).
 */
export function shareWhilePending<T>(load: () => Promise<T>): () => Promise<T> {
  let pending: Promise<T> | null = null;
  return () => {
    if (pending) {
      return pending;
    }
    const started: Promise<T> = load().finally(() => {
      // Only the request that is still the shared one may clear the slot.
      if (pending === started) {
        pending = null;
      }
    });
    pending = started;
    return started;
  };
}
