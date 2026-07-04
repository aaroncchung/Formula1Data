"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LiveTimingBoard } from "@/components/live/LiveTimingBoard";
import { dynamicApi } from "@/lib/api";
import type { LiveDisabledResponse } from "@/types/domain";

type LivePayload = Record<string, unknown> | LiveDisabledResponse;

type LiveState =
  | { state: "loading" }
  | { state: "error"; detail: string }
  | {
      state: "ready";
      payloads: {
        current: LivePayload;
        timing: LivePayload;
        raceControl: LivePayload;
        positions: LivePayload;
        weather: LivePayload;
      };
      updatedAt: string;
    };

export function LiveDataPanel() {
  const [state, setState] = useState<LiveState>({ state: "loading" });

  const load = useCallback(async () => {
    try {
      const [current, timing, raceControl, positions, weather] = await Promise.all([
        dynamicApi.liveCurrentSession(),
        dynamicApi.liveTiming(),
        dynamicApi.liveRaceControl(),
        dynamicApi.livePositions(),
        dynamicApi.liveWeather()
      ]);
      setState({
        state: "ready",
        payloads: { current, timing, raceControl, positions, weather },
        updatedAt: new Date().toLocaleTimeString()
      });
    } catch (error) {
      setState({
        state: "error",
        detail: error instanceof Error ? error.message : "Live API request failed"
      });
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => {
      void load();
    }, 0);
    const timer = window.setInterval(() => {
      void load();
    }, 4000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [load]);

  if (state.state === "loading") {
    return <EmptyState title="Loading live data" detail="Polling the server-side OpenF1 proxy." />;
  }

  if (state.state === "error") {
    return <ErrorState title="Could not load live data" detail={state.detail} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 text-sm text-slate-400">
        <div>Last updated {state.updatedAt}</div>
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded border border-line bg-white/[0.04] px-3 py-2 font-semibold text-white hover:border-aqua/60"
          onClick={() => void load()}
        >
          <RefreshCw size={16} />
          Refresh
        </button>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <ChartPanel title="Current Session">
          <LiveTimingBoard payload={state.payloads.current} />
        </ChartPanel>
        <ChartPanel title="Timing">
          <LiveTimingBoard payload={state.payloads.timing} />
        </ChartPanel>
        <ChartPanel title="Race Control">
          <LiveTimingBoard payload={state.payloads.raceControl} />
        </ChartPanel>
        <ChartPanel title="Positions">
          <LiveTimingBoard payload={state.payloads.positions} />
        </ChartPanel>
        <ChartPanel title="Weather">
          <LiveTimingBoard payload={state.payloads.weather} />
        </ChartPanel>
      </div>
    </div>
  );
}
