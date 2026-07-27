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

type OrderedHandlers<T> = {
  onResult: (value: T) => void;
  onError: (error: unknown) => void;
};

/**
 * Run async work so that only the newest call is allowed to write state.
 *
 * The guard above is the mechanism; this is the thing components use, and it
 * exists so the decision lives somewhere a test can drive. Inlining the
 * `isCurrent` check at each call site meant the ordering rule was only
 * exercised through React, so inverting it changed nothing any test could see.
 * Here the interleaving can be reproduced directly: start two calls, resolve
 * them out of order, and assert which result was committed.
 *
 * `retire()` supersedes without issuing a token -- what a teardown wants.
 */
export function createOrderedRunner() {
  const guard = createRequestGenerationGuard();

  return {
    async run<T>(work: () => Promise<T>, handlers: OrderedHandlers<T>): Promise<T | null> {
      const token = guard.begin();
      try {
        const value = await work();
        if (!guard.isCurrent(token)) {
          return null;
        }
        handlers.onResult(value);
        return value;
      } catch (error) {
        if (!guard.isCurrent(token)) {
          return null;
        }
        handlers.onError(error);
        return null;
      }
    },
    retire() {
      guard.invalidate();
    }
  };
}
