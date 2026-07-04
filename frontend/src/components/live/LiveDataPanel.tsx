"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { LiveTimingBoard } from "@/components/live/LiveTimingBoard";
import { dynamicApi, dynamicApiSourceLabel, isDynamicApiRouteMissing, isLiveDisabled } from "@/lib/api";
import type { LiveDisabledResponse } from "@/types/domain";

type LivePayload = Record<string, unknown> | LiveDisabledResponse;

type LiveState =
  | { state: "loading" }
  | { state: "static-only"; detail: string }
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
      return true;
    } catch (error) {
      if (isDynamicApiRouteMissing(error)) {
        setState({
          state: "static-only",
          detail:
            "This deployment is serving the committed static JSON artifacts only. Live timing requires the Cloudflare Worker API."
        });
        return false;
      }
      setState({
        state: "error",
        detail: error instanceof Error ? error.message : "Live API request failed"
      });
      return true;
    }
  }, []);

  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    const start = async () => {
      const shouldPoll = await load();
      if (!cancelled && shouldPoll) {
        timer = window.setInterval(() => {
          void load();
        }, 4000);
      }
    };
    void start();
    return () => {
      cancelled = true;
      if (timer) {
        window.clearInterval(timer);
      }
    };
  }, [load]);

  if (state.state === "loading") {
    return <EmptyState title="Checking live support" detail={`Looking for the dynamic API at ${dynamicApiSourceLabel()}.`} />;
  }

  if (state.state === "static-only") {
    return (
      <EmptyState
        title="Static-only deployment"
        detail={`${state.detail} Historical pages continue to read committed artifacts from /data without a backend.`}
        action={
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded border border-line bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white hover:border-aqua/60"
            onClick={() => void load()}
          >
            <RefreshCw size={16} />
            Check again
          </button>
        }
      />
    );
  }

  if (state.state === "error") {
    return <ErrorState title="Could not load live data" detail={state.detail} />;
  }

  const payloads = Object.values(state.payloads);
  const liveDisabled = payloads.every(isLiveDisabled);

  if (liveDisabled) {
    const disabled = payloads[0] as LiveDisabledResponse;
    return (
      <EmptyState
        title="Live mode is disabled"
        detail={`The dynamic API is reachable, but live proxying is not enabled for this deployment. ${disabled.reason} ${disabled.setup.join(" ")}`}
        action={
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded border border-line bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white hover:border-aqua/60"
            onClick={() => void load()}
          >
            <RefreshCw size={16} />
            Refresh
          </button>
        }
      />
    );
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
