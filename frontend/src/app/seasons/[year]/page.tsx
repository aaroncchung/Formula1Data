import { loadRouteCatalog } from "@/lib/route-catalog";
import { SeasonPageClient } from "./SeasonPageClient";

export const dynamicParams = false;

export async function generateStaticParams() {
  const catalog = await loadRouteCatalog();
  return catalog.seasons.map((season) => ({ year: String(season.year) }));
}

export default async function SeasonPage({ params }: { params: Promise<{ year: string }> }) {
  const { year: yearParam } = await params;
  return <SeasonPageClient year={Number(yearParam)} />;
}
