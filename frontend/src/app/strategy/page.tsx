"use client";

import { StrategySummary } from "@/components/summary/StrategySummary";
import { SummaryRoute } from "@/components/summary/SummaryRoute";
import { STRATEGY_PATH } from "@/lib/routes";

/** `/strategy?key=11315`, or the most recent published session when no key is given. */
export default function StrategyPage() {
  return (
    <SummaryRoute
      path={STRATEGY_PATH}
      title="Strategy"
      description="Stint structure, compound usage, pit-lane transit timing, and simple post-stop pace estimates."
    >
      {(session) => <StrategySummary view={session.view} />}
    </SummaryRoute>
  );
}
