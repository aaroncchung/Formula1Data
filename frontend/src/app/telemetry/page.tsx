"use client";

import { SummaryRoute } from "@/components/summary/SummaryRoute";
import { TelemetrySummary } from "@/components/summary/TelemetrySummary";
import { TELEMETRY_PATH } from "@/lib/routes";

/** `/telemetry?key=11315`, or the most recent published session when no key is given. */
export default function TelemetryPage() {
  return (
    <SummaryRoute
      path={TELEMETRY_PATH}
      title="Telemetry"
      description="Compare any two drivers and laps of a session, aligned by distance. The session dashboard has the same comparison beside the rest of the session."
    >
      {(session) => <TelemetrySummary view={session.view} />}
    </SummaryRoute>
  );
}
