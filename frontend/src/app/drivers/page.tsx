"use client";

import { DriversSummary } from "@/components/summary/FieldSummaries";
import { SummaryRoute } from "@/components/summary/SummaryRoute";
import { DRIVERS_PATH } from "@/lib/routes";

/** `/drivers?key=11315`, or the most recent published session when no key is given. */
export default function DriversPage() {
  return (
    <SummaryRoute
      path={DRIVERS_PATH}
      title="Drivers"
      description="The field of one session, with each driver's finish, median race pace and ideal lap in it."
    >
      {(session) => <DriversSummary view={session.view} />}
    </SummaryRoute>
  );
}
