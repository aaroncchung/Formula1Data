"use client";

import { useState } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { TelemetryCharts } from "@/components/charts/TelemetryCharts";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { isEmptyState } from "@/lib/static-api-core";
import type { TelemetryIndex } from "@/lib/static-api-core";
import type { EmptyStateResponse, TelemetryComparison } from "@/types/domain";

/** Loads the comparison of two laps: driver and lap number of each. */
export type CompareLaps = (
  driverA: string,
  lapA: number,
  driverB: string,
  lapB: number
) => Promise<TelemetryComparison | EmptyStateResponse>;

export function TelemetryComparePanel({
  initialDriverA,
  initialDriverB,
  initialLapA,
  initialLapB,
  initialComparison,
  initialEmptyState,
  availableLaps = [],
  compare
}: {
  initialDriverA?: string;
  initialDriverB?: string;
  initialLapA?: number;
  initialLapB?: number;
  initialComparison?: TelemetryComparison | null;
  initialEmptyState?: EmptyStateResponse | null;
  availableLaps?: TelemetryIndex["laps"];
  /**
   * Loads a comparison. The page passes one bound to the generation it has
   * pinned, so the laps compared come from the publication the rest of the
   * page was read from.
   */
  compare: CompareLaps;
}) {
  const [driverA, setDriverA] = useState(initialDriverA || initialComparison?.driver_a.driver_code || "");
  const [driverB, setDriverB] = useState(initialDriverB || initialComparison?.driver_b.driver_code || "");
  const [lapA, setLapA] = useState<number | "">(initialLapA || initialComparison?.driver_a.lap_number || "");
  const [lapB, setLapB] = useState<number | "">(initialLapB || initialComparison?.driver_b.lap_number || "");
  const [comparison, setComparison] = useState<TelemetryComparison | null>(initialComparison || null);
  const [emptyState, setEmptyState] = useState<EmptyStateResponse | null>(initialEmptyState || null);
  const [isLoading, setIsLoading] = useState(false);
  const canCompare = Boolean(driverA && driverB && lapA && lapB);
  const drivers = [...new Set(availableLaps.map((item) => item.driver_code))];
  const lapsA = availableLaps.filter((item) => item.driver_code === driverA);
  const lapsB = availableLaps.filter((item) => item.driver_code === driverB);

  function changeDriverA(value: string) {
    setDriverA(value);
    setLapA(availableLaps.find((item) => item.driver_code === value)?.lap_number || "");
  }

  function changeDriverB(value: string) {
    setDriverB(value);
    setLapB(availableLaps.find((item) => item.driver_code === value)?.lap_number || "");
  }

  function submit() {
    if (!canCompare) {
      setEmptyState({
        reason: "Choose two telemetry lap artifacts before comparing.",
        action: "Telemetry comparisons require a driver and lap for both sides."
      });
      setComparison(null);
      return;
    }
    setIsLoading(true);
    setEmptyState(null);
    compare(driverA, Number(lapA), driverB, Number(lapB)).then((result) => {
      if (isEmptyState(result)) {
        setEmptyState(result);
        setComparison(null);
      } else {
        setEmptyState(null);
        setComparison(result);
      }
    }).catch((error: unknown) => {
      setComparison(null);
      setEmptyState({
        reason: "The selected telemetry comparison could not be loaded.",
        action: error instanceof Error ? error.message : "Try another pair of laps."
      });
    }).finally(() => setIsLoading(false));
  }

  return (
    <div className="space-y-4">
      <div className="surface grid gap-3 p-4 md:grid-cols-[1fr_120px_1fr_120px_auto]">
        <label className="text-sm text-slate-400">
          Driver A
          <select
            className="control mt-1 h-10 w-full font-mono"
            value={driverA}
            onChange={(event) => changeDriverA(event.target.value)}
          >
            {drivers.map((driver) => <option key={driver} value={driver}>{driver}</option>)}
          </select>
        </label>
        <label className="text-sm text-slate-400">
          Lap A
          <select
            className="control mt-1 h-10 w-full"
            value={lapA}
            onChange={(event) => setLapA(event.target.value ? Number(event.target.value) : "")}
          >
            {lapsA.map((lap) => <option key={lap.lap_number} value={lap.lap_number}>Lap {lap.lap_number}</option>)}
          </select>
        </label>
        <label className="text-sm text-slate-400">
          Driver B
          <select
            className="control mt-1 h-10 w-full font-mono"
            value={driverB}
            onChange={(event) => changeDriverB(event.target.value)}
          >
            {drivers.map((driver) => <option key={driver} value={driver}>{driver}</option>)}
          </select>
        </label>
        <label className="text-sm text-slate-400">
          Lap B
          <select
            className="control mt-1 h-10 w-full"
            value={lapB}
            onChange={(event) => setLapB(event.target.value ? Number(event.target.value) : "")}
          >
            {lapsB.map((lap) => <option key={lap.lap_number} value={lap.lap_number}>Lap {lap.lap_number}</option>)}
          </select>
        </label>
        <button
          className="h-10 self-end rounded-md bg-redline px-5 text-sm font-bold text-white shadow-lg shadow-redline/15 transition hover:bg-red-500 disabled:opacity-50"
          onClick={submit}
          disabled={isLoading || !canCompare}
          type="button"
        >
          {isLoading ? "Loading…" : "Compare"}
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
          title={`${comparison.driver_a.driver_code} · Lap ${comparison.driver_a.lap_number}  vs  ${comparison.driver_b.driver_code} · Lap ${comparison.driver_b.lap_number}`}
          description="Traces share one distance cursor. Positive time delta means Driver B is behind Driver A."
        >
          <TelemetryCharts comparison={comparison} />
        </ChartPanel>
      ) : null}
    </div>
  );
}

