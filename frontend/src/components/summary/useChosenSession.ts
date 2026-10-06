"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { loadChosenSession, recoverChosenSession } from "@/lib/chosen-session";
import type { ChosenSessionLoad, ReadyChosenSession } from "@/lib/chosen-session";
import { toPublishedFailure } from "@/lib/published/errors";
import { notifyWhenGone } from "@/lib/published/session";
import { publishedSource } from "@/lib/published-source";
import { createRequestGenerationGuard } from "@/lib/request-generation";

export type ChosenSessionState = { readonly status: "loading" } | ChosenSessionLoad;

const LOADING: ChosenSessionState = { status: "loading" };

type Settled = { readonly key: string; readonly load: ChosenSessionLoad };

/**
 * The session a summary page shows: the one with `requestedKey`, or the most
 * recent published one when it is null. The calendar lookup, the pinned view
 * and the single reload when the pinned generation disappears are decided in
 * lib/chosen-session.ts, where they are tested; like `usePublishedSession`,
 * this hook only decides which answer may still be shown.
 */
export function useChosenSession(requestedKey: number | null) {
  const requests = useMemo(() => createRequestGenerationGuard(), []);
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled | null>(null);

  // What a result belongs to. A result is shown only under the key it was
  // loaded for, so choosing another session shows "loading" and never the
  // previous session under the new one's name.
  const key = `${requestedKey ?? "latest"}/${attempt}`;

  useEffect(() => {
    // One token for the first load and a recovery together. Both are dropped
    // once the reader chooses another session or asks again.
    const token = requests.begin();

    function commit(load: ChosenSessionLoad) {
      if (requests.isCurrent(token)) {
        setSettled({ key, load: load.status === "ready" ? watched(load) : load });
      }
    }

    function fail(error: unknown) {
      commit({ status: "no_calendar", failure: toPublishedFailure(error) });
    }

    // Every panel of the page reads through this view. When one of them finds
    // the generation gone, the session is opened again here and all of them
    // start over on the new view, so two generations are never on screen
    // together (rule 1).
    function watched(ready: ReadyChosenSession): ReadyChosenSession {
      const view = notifyWhenGone(ready.view, () => {
        if (requests.isCurrent(token)) {
          recoverChosenSession(publishedSource, ready).then(commit, fail);
        }
      });
      return { ...ready, view };
    }

    loadChosenSession(publishedSource, requestedKey).then(commit, fail);
    return () => requests.invalidate();
  }, [key, requestedKey, requests]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const state: ChosenSessionState = settled?.key === key ? settled.load : LOADING;
  return { state, retry };
}
