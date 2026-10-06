"use client";

import { useState } from "react";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { TelemetryCharts } from "@/components/charts/TelemetryCharts";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { formatMs } from "@/lib/format";
import { isTelemetryNotice } from "@/lib/published/telemetry";
import type { LapRef, TelemetryLapChoice, TelemetryNotice } from "@/lib/published/telemetry";
import type { TelemetryComparison } from "@/lib/telemetry-compare";

/** Loads the comparison of two laps. */
export type CompareLaps = (first: LapRef, second: LapRef) => Promise<TelemetryComparison | TelemetryNotice>;

export function TelemetryComparePanel({
  initialPair,
  initialComparison,
  initialNotice,
  availableLaps,
  compare
}: {
  initialPair: readonly [LapRef, LapRef] | null;
  initialComparison: TelemetryComparison | null;
  initialNotice: TelemetryNotice | null;
  availableLaps: ReadonlyArray<TelemetryLapChoice>;
  /**
   * Loads a comparison. The page passes one bound to the generation it has
   * pinned, so the laps compared come from the publication the rest of the
   * page was read from.
   */
  compare: CompareLaps;
}) {
  const [driverA, setDriverA] = useState(initialPair?.[0].driver ?? "");
  const [driverB, setDriverB] = useState(initialPair?.[1].driver ?? "");
  const [lapA, setLapA] = useState<number | "">(initialPair?.[0].lap ?? "");
  const [lapB, setLapB] = useState<number | "">(initialPair?.[1].lap ?? "");
  const [comparison, setComparison] = useState<TelemetryComparison | null>(initialComparison);
  const [notice, setNotice] = useState<TelemetryNotice | null>(initialNotice);
  const [isLoading, setIsLoading] = useState(false);
  const canCompare = driverA !== "" && driverB !== "" && lapA !== "" && lapB !== "";
  const drivers = [...new Set(availableLaps.map((item) => item.driver_code))];
  const lapsA = availableLaps.filter((item) => item.driver_code === driverA);
  const lapsB = availableLaps.filter((item) => item.driver_code === driverB);

  function changeDriverA(value: string) {
    setDriverA(value);
    setLapA(quickestLap(availableLaps, value) ?? "");
  }

  function changeDriverB(value: string) {
    setDriverB(value);
    setLapB(quickestLap(availableLaps, value) ?? "");
  }

  function submit() {
    if (lapA === "" || lapB === "" || !canCompare) {
      setNotice({
        reason: "Choose two laps before comparing.",
        action: "A comparison needs a driver and a lap on both sides."
      });
      setComparison(null);
      return;
    }
    setIsLoading(true);
    setNotice(null);
    compare({ driver: driverA, lap: lapA }, { driver: driverB, lap: lapB }).then((result) => {
      if (isTelemetryNotice(result)) {
        setNotice(result);
        setComparison(null);
      } else {
        setNotice(null);
        setComparison(result);
      }
    }).catch((error: unknown) => {
      setComparison(null);
      setNotice({
        reason: "The selected telemetry comparison could not be loaded.",
        action: error instanceof Error ? error.message : "Try another pair of laps."
      });
    }).finally(() => setIsLoading(false));
  }

  return (
    <div className="space-y-4">
      <div className="surface grid gap-3 p-4 md:grid-cols-[110px_1fr_110px_1fr_auto]">
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
            {lapsA.map((lap) => <option key={lap.lap_number} value={lap.lap_number}>{lapLabel(lap)}</option>)}
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
            {lapsB.map((lap) => <option key={lap.lap_number} value={lap.lap_number}>{lapLabel(lap)}</option>)}
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
      {notice ? (
        <EmptyState
          title="Telemetry unavailable"
          detail={[notice.reason, notice.action].filter(Boolean).join(" ")}
        />
      ) : null}
      {comparison ? (
        <ChartPanel
          title={`${comparison.driver_a.driver_code} · Lap ${comparison.driver_a.lap_number}  vs  ${comparison.driver_b.driver_code} · Lap ${comparison.driver_b.lap_number}`}
          description={`Traces share one distance cursor. A positive time delta means ${comparison.driver_b.driver_code} is behind ${comparison.driver_a.driver_code}.`}
        >
          <TelemetryCharts comparison={comparison} />
        </ChartPanel>
      ) : null}
    </div>
  );
}

/** A lap as the index describes it, so it can be chosen without knowing its number: "Lap 59 · 1:08.412 · HARD". */
function lapLabel(lap: TelemetryLapChoice): string {
  return [`Lap ${lap.lap_number}`, lap.lap_time_ms === null ? "no time" : formatMs(lap.lap_time_ms), lap.compound]
    .filter((part) => part !== null)
    .join(" · ");
}

/** The lap a driver is first offered: their quickest, or the first listed when none has a time. */
function quickestLap(laps: ReadonlyArray<TelemetryLapChoice>, driver: string): number | null {
  const own = laps.filter((lap) => lap.driver_code === driver);
  const timed = own.filter((lap): lap is TelemetryLapChoice & { lap_time_ms: number } => lap.lap_time_ms !== null && lap.lap_time_ms > 0);
  const quickest = timed.reduce<(typeof timed)[number] | null>(
    (best, lap) => (best === null || lap.lap_time_ms < best.lap_time_ms ? lap : best),
    null
  );
  return quickest?.lap_number ?? own[0]?.lap_number ?? null;
}
