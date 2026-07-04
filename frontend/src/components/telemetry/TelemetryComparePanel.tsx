"use client";

import { useState, useTransition } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { TelemetryCharts } from "@/components/charts/TelemetryCharts";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { api, isEmptyState } from "@/lib/api";
import type { EmptyStateResponse, TelemetryComparison } from "@/types/domain";

export function TelemetryComparePanel({
  initialDriverA,
  initialDriverB,
  initialLapA,
  initialLapB,
  initialComparison,
  initialEmptyState,
  sessionId
}: {
  initialDriverA?: string;
  initialDriverB?: string;
  initialLapA?: number;
  initialLapB?: number;
  initialComparison?: TelemetryComparison | null;
  initialEmptyState?: EmptyStateResponse | null;
  sessionId: string;
}) {
  const [driverA, setDriverA] = useState(initialDriverA || initialComparison?.driver_a.driver_code || "");
  const [driverB, setDriverB] = useState(initialDriverB || initialComparison?.driver_b.driver_code || "");
  const [lapA, setLapA] = useState<number | "">(initialLapA || initialComparison?.driver_a.lap_number || "");
  const [lapB, setLapB] = useState<number | "">(initialLapB || initialComparison?.driver_b.lap_number || "");
  const [comparison, setComparison] = useState<TelemetryComparison | null>(initialComparison || null);
  const [emptyState, setEmptyState] = useState<EmptyStateResponse | null>(initialEmptyState || null);
  const [isPending, startTransition] = useTransition();
  const canCompare = Boolean(driverA && driverB && lapA && lapB);

  function submit() {
    if (!canCompare) {
      setEmptyState({
        reason: "Choose two telemetry lap artifacts before comparing.",
        action: "Telemetry comparisons require a driver and lap for both sides."
      });
      setComparison(null);
      return;
    }
    startTransition(async () => {
      const result = await api.telemetryCompare(sessionId, driverA, Number(lapA), driverB, Number(lapB));
      if (isEmptyState(result)) {
        setEmptyState(result);
        setComparison(null);
      } else {
        setEmptyState(null);
        setComparison(result);
      }
    });
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded border border-line bg-panel p-4 md:grid-cols-[1fr_100px_1fr_100px_auto]">
        <label className="text-sm text-slate-400">
          Driver A
          <input
            className="mt-1 w-full rounded border border-line bg-carbon px-3 py-2 font-mono text-white"
            value={driverA}
            onChange={(event) => setDriverA(event.target.value.toUpperCase())}
          />
        </label>
        <label className="text-sm text-slate-400">
          Lap A
          <input
            className="mt-1 w-full rounded border border-line bg-carbon px-3 py-2 text-white"
            type="number"
            min={1}
            value={lapA}
            onChange={(event) => setLapA(event.target.value ? Number(event.target.value) : "")}
          />
        </label>
        <label className="text-sm text-slate-400">
          Driver B
          <input
            className="mt-1 w-full rounded border border-line bg-carbon px-3 py-2 font-mono text-white"
            value={driverB}
            onChange={(event) => setDriverB(event.target.value.toUpperCase())}
          />
        </label>
        <label className="text-sm text-slate-400">
          Lap B
          <input
            className="mt-1 w-full rounded border border-line bg-carbon px-3 py-2 text-white"
            type="number"
            min={1}
            value={lapB}
            onChange={(event) => setLapB(event.target.value ? Number(event.target.value) : "")}
          />
        </label>
        <button
          className="self-end rounded bg-redline px-4 py-2 font-bold text-white disabled:opacity-60"
          onClick={submit}
          disabled={isPending || !canCompare}
          type="button"
        >
          Compare
        </button>
      </div>
      {emptyState ? (
        <EmptyState
          title="Telemetry unavailable"
          detail={[emptyState.reason, emptyState.action].filter(Boolean).join(" ")}
        />
      ) : null}
      {comparison ? (
        <ChartPanel
          title={`${comparison.driver_a.driver_code} lap ${comparison.driver_a.lap_number} vs ${comparison.driver_b.driver_code} lap ${comparison.driver_b.lap_number}`}
          description="Aligned by distance and downsampled for browser performance."
        >
          <TelemetryCharts comparison={comparison} />
        </ChartPanel>
      ) : null}
    </div>
  );
}

