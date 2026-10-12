"use client";

import { useEffect, useState } from "react";

import { LapTimesTab } from "@/components/published/LapTimesTab";
import { OverviewTab } from "@/components/published/OverviewTab";
import { PerformanceTab } from "@/components/published/PerformanceTab";
import { PositionReplayTab } from "@/components/published/PositionReplayTab";
import { RaceControlTab } from "@/components/published/RaceControlTab";
import { RacePaceTab } from "@/components/published/RacePaceTab";
import { ResultsTab } from "@/components/published/ResultsTab";
import type { TabProps } from "@/components/published/SessionTab";
import { StrategyTab } from "@/components/published/StrategyTab";
import { TelemetryTab } from "@/components/published/TelemetryTab";
import { WeatherTab } from "@/components/published/WeatherTab";
import { tabAvailability } from "@/lib/published/artifacts";
import type { SessionView } from "@/lib/published/client";
import { DEFAULT_SESSION_TAB, SESSION_TABS, hashOfTab, tabFromHash } from "@/lib/published/tabs";
import type { SessionTabId } from "@/lib/published/tabs";

const TAB_BODIES: Readonly<Record<SessionTabId, (props: TabProps) => React.ReactNode>> = {
  overview: OverviewTab,
  "lap-times": LapTimesTab,
  "race-pace": RacePaceTab,
  performance: PerformanceTab,
  strategy: StrategyTab,
  telemetry: TelemetryTab,
  "position-replay": PositionReplayTab,
  weather: WeatherTab,
  "race-control": RaceControlTab,
  results: ResultsTab
};

type Tabs = { readonly active: SessionTabId; readonly opened: ReadonlySet<SessionTabId> };

/** The same tabs with one more in front. */
function opening(tabs: Tabs, tab: SessionTabId): Tabs {
  if (tabs.active === tab) {
    return tabs;
  }
  return { active: tab, opened: tabs.opened.has(tab) ? tabs.opened : new Set(tabs.opened).add(tab) };
}

/**
 * The tabs of one session view.
 *
 * A tab is mounted the first time it is opened and stays mounted afterwards,
 * rendering nothing while another tab is in front. Its artifacts are
 * therefore requested only if someone looks, and once for each view: going
 * back to a tab shows what it already has. When the view is replaced, after
 * its generation went, every opened tab reads again from the new one.
 *
 * The tab in front is also in the URL, as its fragment, so a link opens on
 * the tab it was copied from. That tab is then the first and only one to be
 * read: a link to the results does not load the overview on the way.
 */
export function PublishedSessionTabs({ view }: { view: SessionView }) {
  // This component first renders in the browser, after the session has
  // loaded, so the fragment is there to read when its state is created.
  const [tabs, setTabs] = useState<Tabs>(() => {
    const first = (typeof window === "undefined" ? null : tabFromHash(window.location.hash)) ?? DEFAULT_SESSION_TAB;
    return { active: first, opened: new Set([first]) };
  });

  useEffect(() => {
    // The fragment changed without a click on a tab: it was edited, or the
    // browser went back to an entry that names another tab.
    function followHash() {
      const named = tabFromHash(window.location.hash);
      if (named) {
        setTabs((current) => opening(current, named));
      }
    }
    window.addEventListener("hashchange", followHash);
    return () => window.removeEventListener("hashchange", followHash);
  }, []);

  function select(tab: SessionTabId) {
    setTabs((current) => opening(current, tab));
    // Replaced, not pushed: moving between tabs is not a step to go back
    // through. The query string is kept, because it is what names the session.
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${hashOfTab(tab)}`);
  }

  return (
    <div className="space-y-5">
      <div className="surface overflow-x-auto p-1">
        <div className="flex min-w-max gap-1" role="tablist" aria-label="Session views">
          {SESSION_TABS.map((tab) => {
            const selected = tabs.active === tab.id;
            // Known from the manifest, before anything is asked for.
            const available = tabAvailability(view, tab.id).available;
            return (
              <button
                key={tab.id}
                id={`session-tab-${tab.id}`}
                className={`rounded px-3 py-2 text-sm font-semibold ${
                  selected
                    ? "bg-redline text-white"
                    : available
                      ? "text-slate-400 hover:bg-white/[0.05] hover:text-white"
                      : "text-slate-600 hover:bg-white/[0.05] hover:text-slate-400"
                }`}
                onClick={() => select(tab.id)}
                type="button"
                role="tab"
                aria-selected={selected}
                title={available ? undefined : "Not part of this session's published data"}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>
      {SESSION_TABS.map((tab) => {
        if (!tabs.opened.has(tab.id)) {
          return null;
        }
        const Body = TAB_BODIES[tab.id];
        return <Body key={tab.id} view={view} active={tabs.active === tab.id} />;
      })}
    </div>
  );
}
