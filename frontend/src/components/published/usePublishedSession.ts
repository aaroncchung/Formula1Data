"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { publishedData } from "@/lib/published/browser";
import { toPublishedFailure } from "@/lib/published/errors";
import { loadSession, notifyWhenGone, recoverSession } from "@/lib/published/session";
import type { ReadySession, SessionLoad } from "@/lib/published/session";
import { createRequestGenerationGuard } from "@/lib/request-generation";

export type SessionState = { readonly status: "loading" } | SessionLoad;

const LOADING: SessionState = { status: "loading" };

type Settled = { readonly key: string; readonly load: SessionLoad };

/**
 * One session for a page: the index lookup, the pinned view, and the single
 * reload when the pinned generation disappears. The decisions are made in
 * lib/published/session.ts, where they are tested; this hook only decides
 * which answer may still be shown.
 */
export function usePublishedSession(year: number, round: number, sessionType: string) {
  const requests = useMemo(() => createRequestGenerationGuard(), []);
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled | null>(null);

  // What a result belongs to. A result is shown only under the key it was
  // loaded for, so "loading" needs no state of its own: it is simply the
  // absence of a result for the current key.
  const key = `${year}/${round}/${sessionType}/${attempt}`;

  useEffect(() => {
    // One token for the whole life of this route: the first load and a
    // recovery belong together, and both are dropped once the query string
    // changes or the page asks again. Without this a slow answer for the
    // session the user has left would replace the one they are looking at.
    const token = requests.begin();

    function commit(load: SessionLoad) {
      if (requests.isCurrent(token)) {
        setSettled({ key, load: load.status === "ready" ? watched(load) : load });
      }
    }

    function fail(error: unknown) {
      commit({ status: "failed", entry: null, failure: toPublishedFailure(error) });
    }

    // Tabs read through this view and do not report upwards. When one of them
    // finds the generation gone, the session is opened again here and every
    // tab starts over on the new view, so two generations are never on screen
    // together.
    function watched(ready: ReadySession): ReadySession {
      const view = notifyWhenGone(ready.view, () => {
        if (requests.isCurrent(token)) {
          recoverSession(publishedData, ready).then(commit, fail);
        }
      });
      return { ...ready, view };
    }

    loadSession(publishedData, { year, round, sessionType }).then(commit, fail);
    return () => requests.invalidate();
  }, [key, requests, round, sessionType, year]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const state: SessionState = settled?.key === key ? settled.load : LOADING;
  return { state, retry };
}
