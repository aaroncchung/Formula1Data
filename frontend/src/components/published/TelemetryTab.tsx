"use client";

import { useCallback } from "react";

import { EmptyState } from "@/components/dashboard/EmptyState";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { TelemetryComparePanel, type CompareLaps } from "@/components/telemetry/TelemetryComparePanel";
import type { SessionView } from "@/lib/published/client";
import { compareTelemetry, readTelemetry, type SessionTelemetry } from "@/lib/published/telemetry";

/**
 * Opening the tab reads the index of telemetry laps and the files of the two
 * drivers whose laps it starts on. A later comparison reads a driver's file
 * only if the page does not have it yet.
 */
export function TelemetryTab(props: TabProps) {
  const { view } = props;
  return (
    <SessionTab {...props} tab="telemetry" name="telemetry" read={readTelemetry}>
      {(telemetry) => <TelemetryLaps view={view} telemetry={telemetry} />}
    </SessionTab>
  );
}

/**
 * The lap comparison from what `readTelemetry` read. The body of the
 * dashboard's telemetry tab, and of the telemetry page, which shows the same
 * thing for a session the reader chooses.
 */
export function TelemetryLaps({ view, telemetry }: { view: SessionView; telemetry: SessionTelemetry }) {
  // Bound to the view, so a comparison asked for later comes from the same
  // generation as the index the laps were chosen from.
  const compare = useCallback<CompareLaps>((first, second) => compareTelemetry(view, first, second), [view]);
  const { laps, pair, comparison, notice } = telemetry;
  if (laps.length === 0) {
    return <EmptyState title="No telemetry laps" detail="This session was published without telemetry for any lap." />;
  }
  const drivers = new Set(laps.map((lap) => lap.driver_code)).size;
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        {laps.length.toLocaleString("en-US")} laps of {drivers} {drivers === 1 ? "driver" : "drivers"} have telemetry.
        Pick any two to compare. A driver&apos;s laps are one file of about a megabyte, loaded the first time one of
        them is compared.
      </p>
      <TelemetryComparePanel
        availableLaps={laps}
        initialPair={pair}
        initialComparison={comparison}
        initialNotice={notice}
        compare={compare}
      />
    </div>
  );
}
