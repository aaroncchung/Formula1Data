"use client";

import { useState } from "react";

import { LapTimesTab } from "@/components/published/LapTimesTab";
import { ResultsTab } from "@/components/published/ResultsTab";
import type { SessionView } from "@/lib/published/client";

const TABS = [
  { id: "results", label: "Results" },
  { id: "lap-times", label: "Lap times" }
] as const;

type TabId = (typeof TABS)[number]["id"];

/**
 * The tabs of one session view.
 *
 * A tab is mounted the first time it is opened and stays mounted afterwards,
 * rendering nothing while another tab is in front. Its artifacts are
 * therefore requested only if someone looks, and once for each view: going
 * back to a tab shows what it already has. When the view is replaced, after
 * its generation went, every opened tab reads again from the new one.
 */
export function PublishedSessionTabs({ view }: { view: SessionView }) {
  const [active, setActive] = useState<TabId>("results");
  const [opened, setOpened] = useState<ReadonlySet<TabId>>(() => new Set<TabId>(["results"]));

  function select(tab: TabId) {
    setActive(tab);
    setOpened((current) => (current.has(tab) ? current : new Set(current).add(tab)));
  }

  return (
    <div className="space-y-5">
      <div className="surface overflow-x-auto p-1">
        <div className="flex min-w-max gap-1" role="tablist" aria-label="Session views">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              id={`session-tab-${tab.id}`}
              className={`rounded px-3 py-2 text-sm font-semibold ${
                active === tab.id ? "bg-redline text-white" : "text-slate-400 hover:bg-white/[0.05] hover:text-white"
              }`}
              onClick={() => select(tab.id)}
              type="button"
              role="tab"
              aria-selected={active === tab.id}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      {opened.has("results") ? <ResultsTab view={view} active={active === "results"} /> : null}
      {opened.has("lap-times") ? <LapTimesTab view={view} active={active === "lap-times"} /> : null}
    </div>
  );
}
