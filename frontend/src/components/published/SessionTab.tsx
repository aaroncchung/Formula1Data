"use client";

import { ArtifactPanel } from "@/components/published/ArtifactPanel";
import { usePublishedArtifact } from "@/components/published/usePublishedArtifact";
import type { SessionView } from "@/lib/published/client";
import type { SessionTabId } from "@/lib/published/tabs";

/** What every tab is given: the pinned view to read from, and whether it is the one in front. */
export type TabProps = { view: SessionView; active: boolean };

type SessionTabProps<T> = TabProps & {
  tab: SessionTabId;
  /** What the tab shows, as it reads in a sentence: "results", "lap times". */
  name: string;
  /** A module-level reader from lib/published; see `usePublishedArtifact` for why it must not change. */
  read: (view: SessionView) => Promise<T>;
  children: (data: T) => React.ReactNode;
};

/**
 * One tab: its read, and its body in whichever state the read is in.
 *
 * The read starts when the tab is first mounted, which is when it is first
 * opened, and it is kept while another tab is in front: coming back shows
 * what is already here. What is drawn from it is not kept, so a chart is not
 * laid out while nobody can see it.
 */
export function SessionTab<T>({ view, active, tab, name, read, children }: SessionTabProps<T>) {
  const { artifact, retry } = usePublishedArtifact(view, read);
  if (!active) {
    return null;
  }
  return (
    <ArtifactPanel tab={tab} name={name} artifact={artifact} onRetry={retry}>
      {children}
    </ArtifactPanel>
  );
}
