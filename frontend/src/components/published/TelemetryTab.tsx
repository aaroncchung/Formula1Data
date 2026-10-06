"use client";

import { useCallback } from "react";

import { EmptyState } from "@/components/dashboard/EmptyState";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { TelemetryComparePanel, type CompareLaps } from "@/components/telemetry/TelemetryComparePanel";
import type { SessionView } from "@/lib/published/client";
import { compareTelemetry, readTelemetry, type SessionTelemetry } from "@/lib/published/telemetry";

/**
 * Opening the tab reads the index of telemetry laps and the two laps of the
 * comparison it starts on. Every later comparison reads the two laps it
 * compares and nothing else, out of the thousand and more a race has.
 */
export function TelemetryTab(props: TabProps) {
  const { view } = props;
  return (
    <SessionTab {...props} tab="telemetry" name="telemetry" read={readTelemetry}>
      {(telemetry) => <Telemetry view={view} telemetry={telemetry} />}
    </SessionTab>
  );
}

function Telemetry({ view, telemetry }: { view: SessionView; telemetry: SessionTelemetry }) {
  // Bound to the view, so a comparison asked for later comes from the same
  // generation as the index the laps were chosen from.
  const compare = useCallback<CompareLaps>(
    (driverA, lapA, driverB, lapB) =>
      compareTelemetry(view, { driver: driverA, lap: lapA }, { driver: driverB, lap: lapB }),
    [view]
  );
  const { laps, pair, comparison, notice } = telemetry;
  if (laps.length === 0) {
    return <EmptyState title="No telemetry laps" detail="This session was published without telemetry for any lap." />;
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        {laps.length.toLocaleString("en-US")} laps have telemetry. Pick any two to compare; each comparison loads only
        the two laps it compares.
      </p>
      <TelemetryComparePanel
        // Only names the build-time site's files, which this page does not read.
        sessionId={String(view.pointer.session_key)}
        availableLaps={laps}
        initialDriverA={pair?.[0].driver}
        initialLapA={pair?.[0].lap}
        initialDriverB={pair?.[1].driver}
        initialLapB={pair?.[1].lap}
        initialComparison={comparison}
        initialEmptyState={notice}
        compare={compare}
      />
    </div>
  );
}
