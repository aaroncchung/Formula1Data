"use client";

import Link from "next/link";
import { useCallback } from "react";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { LoadingState } from "@/components/dashboard/LoadingState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { api } from "@/lib/api";
import { seasonHref } from "@/lib/season-routes";
import { useRuntimeData } from "@/lib/use-runtime-data";

export default function SeasonsPage() {
  const load = useCallback(() => api.seasons(), []);
  const state = useRuntimeData(load);
  if (state.state === "loading") return <LoadingState label="Loading current season catalog" />;
  if (state.state === "error") return <ErrorState title="Could not load seasons" detail={state.detail} />;
  return (
    <div>
      <PageHeader title="Seasons" description="Historical seasons currently published through the artifact API." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {state.data.map((season) => (
          <Link key={season.year} href={seasonHref(season.year)} className="rounded border border-line bg-panel p-5 hover:border-redline/60">
            <div className="text-3xl font-black text-white">{season.year}</div>
            <div className="mt-3 text-sm text-slate-400">{season.ingested_meeting_count}/{season.meeting_count} meetings ingested</div>
            {season.is_sample ? <div className="mt-3 text-xs font-bold uppercase text-amber">Demo data</div> : null}
          </Link>
        ))}
      </div>
    </div>
  );
}
