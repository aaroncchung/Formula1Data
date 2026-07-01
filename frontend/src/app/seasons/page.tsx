import Link from "next/link";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { api, safeApi } from "@/lib/api-server";

export default async function SeasonsPage() {
  const seasons = await safeApi(() => api.seasons());
  if (!seasons.ok) {
    return <ErrorState title="Could not load seasons" detail={`${seasons.error.message}: ${seasons.apiBaseUrl}`} />;
  }
  return (
    <div>
      <PageHeader title="Seasons" description="Historical season artifacts available in static data." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {seasons.data.map((season) => (
          <Link key={season.year} href={`/seasons/${season.year}`} className="rounded border border-line bg-panel p-5 hover:border-redline/60">
            <div className="text-3xl font-black text-white">{season.year}</div>
            <div className="mt-3 text-sm text-slate-400">
              {season.ingested_meeting_count}/{season.meeting_count} meetings ingested
            </div>
            {season.is_sample ? <div className="mt-3 text-xs font-bold uppercase text-amber">Demo data</div> : null}
          </Link>
        ))}
      </div>
    </div>
  );
}
