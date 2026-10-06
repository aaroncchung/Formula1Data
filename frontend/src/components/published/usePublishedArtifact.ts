"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { SessionView } from "@/lib/published/client";
import { toPublishedFailure } from "@/lib/published/errors";
import type { PublishedFailure } from "@/lib/published/errors";
import { createOrderedRunner } from "@/lib/request-generation";

export type Artifact<T> =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: T }
  | { readonly status: "failed"; readonly failure: PublishedFailure };

const LOADING = { status: "loading" } as const;

type Settled<T> = {
  readonly view: SessionView;
  readonly attempt: number;
  readonly artifact: Artifact<T>;
};

/**
 * What one tab reads from a view, loaded when the tab first mounts. A failure
 * stays inside the tab that asked.
 *
 * `read` must be the same function on every render (a module-level reader
 * from lib/published/artifacts.ts): a new one each time would read again on
 * every render.
 */
export function usePublishedArtifact<T>(view: SessionView, read: (view: SessionView) => Promise<T>) {
  const requests = useMemo(() => createOrderedRunner(), []);
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    void requests.run(() => read(view), {
      onResult: (data) => setSettled({ view, attempt, artifact: { status: "ready", data } }),
      onError: (error) =>
        setSettled({ view, attempt, artifact: { status: "failed", failure: toPublishedFailure(error) } })
    });
    return () => requests.retire();
  }, [attempt, read, requests, view]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  // A result is shown only for the view it was read from. When the session is
  // reopened on another generation the old result stops matching, and the tab
  // is loading again without having shown one generation's rows under
  // another's header.
  const artifact: Artifact<T> =
    settled && settled.view === view && settled.attempt === attempt ? settled.artifact : LOADING;
  return { artifact, retry };
}
