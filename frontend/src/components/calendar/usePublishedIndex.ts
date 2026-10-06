"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { publishedData } from "@/lib/published/browser";
import { toPublishedFailure } from "@/lib/published/errors";
import type { PublishedFailure } from "@/lib/published/errors";
import type { PublishedIndex } from "@/lib/published/types";
import { createOrderedRunner } from "@/lib/request-generation";

export type IndexState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly index: PublishedIndex }
  | { readonly status: "failed"; readonly failure: PublishedFailure };

const LOADING: IndexState = { status: "loading" };

type Settled = { readonly attempt: number; readonly state: IndexState };

/**
 * The published calendar, read in the browser when the component mounts.
 *
 * `watch` is for a component that outlives the page, such as the bar at the
 * top: the calendar is read again whenever the value changes. What was read
 * before stays on screen meanwhile, so a navigation does not blank the picker.
 */
export function usePublishedIndex(watch = "") {
  const requests = useMemo(() => createOrderedRunner(), []);
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled | null>(null);

  useEffect(() => {
    void requests.run(() => publishedData.index(), {
      onResult: (index) => setSettled({ attempt, state: { status: "ready", index } }),
      onError: (error) =>
        setSettled({ attempt, state: { status: "failed", failure: toPublishedFailure(error) } })
    });
    return () => requests.retire();
  }, [attempt, requests, watch]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  // A result is shown only for the attempt it answered, so asking again shows
  // "loading" and not the failure that was asked about.
  const state: IndexState = settled && settled.attempt === attempt ? settled.state : LOADING;
  return { state, retry };
}
