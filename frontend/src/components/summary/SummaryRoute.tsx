"use client";

import { Suspense } from "react";

import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { SummaryPage } from "@/components/summary/SummaryPage";
import type { ReadySession } from "@/lib/published/session";

type SummaryRouteProps = {
  path: string;
  title: string;
  description: string;
  children: (session: ReadySession) => React.ReactNode;
};

/**
 * A summary page as a route: `SummaryPage` inside the Suspense boundary that
 * reading the address needs. The query string does not exist while the shell is
 * exported, so the exported HTML is the fallback, with the page's real
 * heading, and the session renders in the browser.
 */
export function SummaryRoute({ path, title, description, children }: SummaryRouteProps) {
  return (
    <Suspense
      fallback={
        <div>
          <PageHeader title={title} description={description} />
          <LoadingState label="Loading session" />
        </div>
      }
    >
      <SummaryPage path={path} title={title} description={description}>
        {children}
      </SummaryPage>
    </Suspense>
  );
}
