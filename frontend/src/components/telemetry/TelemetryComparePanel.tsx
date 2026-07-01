"use client";

import { useState, useTransition } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { TelemetryCharts } from "@/components/charts/TelemetryCharts";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { api, isEmptyState } from "@/lib/api";
import type { TelemetryComparison } from "@/types/domain";

export function TelemetryComparePanel({
  initialComparison,
  sessionId
}: {
  initialComparison?: TelemetryComparison | null;
  sessionId: string;
}) {
  const [driverA, setDriverA] = useState("VER");
  const [driverB, setDriverB] = useState("LEC");
  const [lapA, setLapA] = useState(6);
  const [lapB, setLapB] = useState(7);
  const [comparison, setComparison] = useState<TelemetryComparison | null>(initialComparison || null);
  const [emptyReason, setEmptyReason] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function submit() {
    startTransition(async () => {
      const result = await api.telemetryCompare(sessionId, driverA, lapA, driverB, lapB);
      if (isEmptyState(result)) {
        setEmptyReason(result.reason);
        setComparison(null);
      } else {
        setEmptyReason(null);
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
            onChange={(event) => setLapA(Number(event.target.value))}
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
            onChange={(event) => setLapB(Number(event.target.value))}
          />
        </label>
        <button
          className="self-end rounded bg-redline px-4 py-2 font-bold text-white disabled:opacity-60"
          onClick={submit}
          disabled={isPending}
          type="button"
        >
          Compare
        </button>
      </div>
      {emptyReason ? <EmptyState title="Telemetry unavailable" detail={emptyReason} /> : null}
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

