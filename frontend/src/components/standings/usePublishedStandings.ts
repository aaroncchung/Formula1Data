"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { publishedData } from "@/lib/published/browser";
import { toPublishedFailure } from "@/lib/published/errors";
import type { PublishedFailure } from "@/lib/published/errors";
import type { Standings } from "@/lib/published/types";
import { createOrderedRunner } from "@/lib/request-generation";

export type StandingsState =
  | { readonly status: "loading" }
  /** `standings` is null when none are published for the season, which is not a failure. */
  | { readonly status: "ready"; readonly standings: Standings | null }
  | { readonly status: "failed"; readonly failure: PublishedFailure };

const LOADING: StandingsState = { status: "loading" };

type Settled = { readonly key: string; readonly state: StandingsState };

/**
 * The published standings of one season, read in the browser on every visit.
 * A correction that does not advance the round is therefore on the page the
 * next time it is opened, with no new build of the site.
 */
export function usePublishedStandings(year: number) {
  const requests = useMemo(() => createOrderedRunner(), []);
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled | null>(null);

  // A result is shown only under the season it was read for, so changing the
  // season shows "loading" and never last season's table under this one's name.
  const key = `${year}/${attempt}`;

  useEffect(() => {
    void requests.run(() => publishedData.standings(year), {
      onResult: (standings) => setSettled({ key, state: { status: "ready", standings } }),
      onError: (error) => setSettled({ key, state: { status: "failed", failure: toPublishedFailure(error) } })
    });
    return () => requests.retire();
  }, [key, requests, year]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const state: StandingsState = settled?.key === key ? settled.state : LOADING;
  return { state, retry };
}
