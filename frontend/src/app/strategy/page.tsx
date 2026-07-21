"use client";

import { useCallback } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { PitStopTimeline } from "@/components/session/PitStopTimeline";
import { StintTimeline } from "@/components/session/StintTimeline";
import { StrategyAnalysis } from "@/components/session/StrategyAnalysis";
import { api } from "@/lib/api";
import { useRuntimeData } from "@/lib/use-runtime-data";

export default function StrategyPage() {
  const load = useCallback(async () => {
    const session = await api.primarySession();
    const [stints, pitStops, strategy] = await Promise.all([api.stints(session.session_id), api.pitStops(session.session_id), api.strategy(session.session_id)]);
    return { stints, pitStops, strategy };
  }, []);
  const state = useRuntimeData(load);
  if (state.state === "loading") return <LoadingState label="Loading current strategy artifacts" />;
  if (state.state === "error") return <ErrorState title="Could not load strategy" detail={state.detail} />;
  return <div><PageHeader title="Strategy" description="Stint structure, compound usage, pit-lane transit timing, and simple post-stop pace estimates." /><div className="space-y-5"><ChartPanel title="Stint Timeline"><StintTimeline stints={state.data.stints} /></ChartPanel><ChartPanel title="Pit Stop Timing"><PitStopTimeline stops={state.data.pitStops} /></ChartPanel><ChartPanel title="Strategy Analysis" description="Compound usage, stops, and simple post-stop pace estimates."><StrategyAnalysis strategy={state.data.strategy} pitStops={state.data.pitStops} /></ChartPanel></div></div>;
}
