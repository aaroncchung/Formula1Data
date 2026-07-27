/**
 * Orders overlapping async responses so only the newest one is allowed to
 * write state.
 *
 * A component that both polls and responds to user actions can have several
 * requests in flight at once -- `SessionIngestionPanel` polls status every 3 s
 * against a 12 s request timeout, so a slow poll can still land after a newer
 * one has already returned. Without an ordering rule the stale response wins
 * simply by arriving last.
 *
 * `begin()` supersedes every earlier token, so callers drop their result when
 * `isCurrent()` is false. `invalidate()` supersedes without issuing a new
 * token, which is what a teardown wants: on unmount, or when the identity the
 * requests were made against changes.
 */
export function createRequestGenerationGuard() {
  let generation = 0;

  return {
    begin() {
      generation += 1;
      return generation;
    },
    invalidate() {
      generation += 1;
    },
    isCurrent(token: number) {
      return token === generation;
    }
  };
}
