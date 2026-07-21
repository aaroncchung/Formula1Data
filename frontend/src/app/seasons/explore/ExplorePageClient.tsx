"use client";

import { useSearchParams } from "next/navigation";

import { MeetingPageClient } from "@/app/seasons/[year]/[round]/MeetingPageClient";
import { SeasonPageClient } from "@/app/seasons/[year]/SeasonPageClient";
import { ErrorState } from "@/components/dashboard/ErrorState";
import { SessionIngestionPanel } from "@/components/session/SessionIngestionPanel";
import { parseExploreTarget } from "@/lib/season-routes";

export function ExplorePageClient() {
  const target = parseExploreTarget(useSearchParams());
  if (target.kind === "error") {
    return <ErrorState title="Invalid season route" detail={target.detail} />;
  }
  if (target.kind === "season") {
    return <SeasonPageClient year={target.year} />;
  }
  if (target.kind === "meeting") {
    return <MeetingPageClient year={target.year} round={target.round} />;
  }
  return (
    <SessionIngestionPanel
      key={`${target.year}-${target.round}-${target.session}`}
      year={target.year}
      round={target.round}
      session={target.session}
      staticCommand={`python -m pipeline ingest-session --year ${target.year} --event ${target.round} --session ${target.session}`}
    />
  );
}
