"use client";

import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { PerformanceAnalysis } from "@/components/session/PerformanceAnalysis";
import { readPerformance } from "@/lib/published/artifacts";

/**
 * Six analyses, any of which a generation may leave out. One that is missing
 * arrives here as null and is listed as not shown; it is not an error and
 * costs the tab nothing else.
 */
export function PerformanceTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="performance" name="performance analysis" read={readPerformance}>
      {(data) => <PerformanceAnalysis {...data} />}
    </SessionTab>
  );
}
