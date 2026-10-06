"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { PitStopTimeline } from "@/components/session/PitStopTimeline";
import { StintTimeline } from "@/components/session/StintTimeline";
import { StrategyAnalysis } from "@/components/session/StrategyAnalysis";
import { readStrategy, type SessionStrategy } from "@/lib/published/artifacts";

export function StrategyTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="strategy" name="strategy" read={readStrategy}>
      {(data) => <StrategyPanels {...data} />}
    </SessionTab>
  );
}

/**
 * A session's strategy from what `readStrategy` read. The body of the
 * dashboard's strategy tab, and of the strategy page, which shows the same
 * thing for a session the reader chooses.
 */
export function StrategyPanels({ stints, pitStops, strategy }: SessionStrategy) {
  return (
    <div className="space-y-5">
      <ChartPanel title="Stint Timeline">
        {stints.length ? <StintTimeline stints={stints} /> : <p className="text-sm text-slate-400">No stints were recorded.</p>}
      </ChartPanel>
      <ChartPanel title="Pit Stop Timeline">
        {/* The same lap axis as the stints above, so a stop lines up with the stint it ends. */}
        <PitStopTimeline stops={pitStops} lastLap={Math.max(0, ...stints.map((stint) => stint.end_lap))} />
      </ChartPanel>
      <ChartPanel title="Strategy Analysis" description="Compound usage, pit-lane time, pit loss, and the pace change across each driver's first stop.">
        <StrategyAnalysis strategy={strategy} pitStops={pitStops} />
      </ChartPanel>
    </div>
  );
}
