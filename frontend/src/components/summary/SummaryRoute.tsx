"use client";

import { Suspense } from "react";

import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { SummaryPage } from "@/components/summary/SummaryPage";
import type { ReadyChosenSession } from "@/lib/chosen-session";

type SummaryRouteProps = {
  path: string;
  title: string;
  description: string;
  children: (session: ReadyChosenSession) => React.ReactNode;
};

/**
 * A summary page as a route: `SummaryPage` inside the Suspense boundary that
 * reading `?key=` needs. The query string does not exist while the shell is
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
