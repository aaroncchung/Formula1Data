import { loadRouteCatalog } from "@/lib/route-catalog";
import { MeetingPageClient } from "./MeetingPageClient";

export const dynamicParams = false;

export async function generateStaticParams() {
  const catalog = await loadRouteCatalog();
  const rounds = new Map<string, { year: string; round: string }>();
  for (const meeting of catalog.meetings) {
    rounds.set(`${meeting.year}-${meeting.round}`, {
      year: String(meeting.year),
      round: String(meeting.round)
    });
  }
  return Array.from(rounds.values());
}

export default async function MeetingPage({ params }: { params: Promise<{ year: string; round: string }> }) {
  const { year: yearParam, round: roundParam } = await params;
  return <MeetingPageClient year={Number(yearParam)} round={Number(roundParam)} />;
}
