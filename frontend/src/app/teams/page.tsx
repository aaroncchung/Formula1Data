"use client";

import { TeamsSummary } from "@/components/summary/FieldSummaries";
import { SummaryRoute } from "@/components/summary/SummaryRoute";
import { TEAMS_PATH } from "@/lib/routes";

/** `/teams?key=11315`, or the most recent published session when no key is given. */
export default function TeamsPage() {
  return (
    <SummaryRoute
      path={TEAMS_PATH}
      title="Teams"
      description="The line-ups of one session, with the points each team scored in it, its best finish, and how many laps counted towards its race pace."
    >
      {(session) => <TeamsSummary view={session.view} />}
    </SummaryRoute>
  );
}
