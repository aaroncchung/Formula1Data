"use client";

import { CoverageBadge } from "@/components/published/Coverage";
import { GenerationNote } from "@/components/published/GenerationNote";
import { PublishedSessionTabs } from "@/components/published/PublishedSessionTabs";
import { SessionHeader } from "@/components/published/SessionHeader";
import { SessionStates } from "@/components/published/SessionStates";
import { usePublishedSession } from "@/components/published/usePublishedSession";
import { sessionHref } from "@/lib/published/lookup";
import type { SessionAddress } from "@/lib/published/lookup";

/**
 * One session, loaded in the browser from published data.
 *
 * The page is a static shell: nothing about any session is known when the
 * site is built, so a session published tomorrow has a page today (AR-07).
 * What each state of the load looks like is in `SessionStates`, which the
 * pages that summarise a session share. This page's own part is the session's
 * heading above and the tabs below.
 */
export function PublishedSession({ address }: { address: SessionAddress }) {
  const { state, retry } = usePublishedSession(address);
  return (
    <SessionStates
      state={state}
      address={address}
      onRetry={retry}
      // The heading comes from the calendar where it places the session, so
      // it reads the same whether the session turned out to be published,
      // unpublished or broken. Until the session is known there is none.
      above={(heading, view) =>
        heading ? (
          <SessionHeader heading={heading} actions={view ? <CoverageBadge coverage={view.pointer.coverage} /> : undefined} />
        ) : null
      }
    >
      {({ view }) => (
        <>
          <PublishedSessionTabs view={view} />
          <GenerationNote
            view={view}
            permanentHref={
              address.kind === "route" ? sessionHref({ kind: "key", sessionKey: view.pointer.session_key }) : null
            }
          />
        </>
      )}
    </SessionStates>
  );
}
