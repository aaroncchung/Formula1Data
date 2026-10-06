"use client";

import { EmptyState } from "@/components/dashboard/EmptyState";
import { ArtifactPanel } from "@/components/published/ArtifactPanel";
import { usePublishedArtifact } from "@/components/published/usePublishedArtifact";
import { DriverBadge, TeamColorPill } from "@/components/session/Badges";
import { formatMs } from "@/lib/format";
import type { SessionView } from "@/lib/published/client";
import { driverCards, readField, teamCards } from "@/lib/session-summaries";
import type { DriverCard, TeamCard } from "@/lib/session-summaries";

/** The drivers of one session, each with their finish, race pace and ideal lap in it. */
export function DriversSummary({ view }: { view: SessionView }) {
  const { artifact, retry } = usePublishedArtifact(view, readField);
  return (
    <ArtifactPanel name="drivers" artifact={artifact} onRetry={retry}>
      {(field) => {
        const cards = driverCards(field);
        return cards.length === 0 ? (
          <EmptyState title="No drivers" detail="This session was published without a driver list." />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {cards.map((card) => (
              <DriverCardView key={card.driver.code} card={card} />
            ))}
          </div>
        );
      }}
    </ArtifactPanel>
  );
}

function DriverCardView({ card }: { card: DriverCard }) {
  const { driver } = card;
  return (
    <div className="surface overflow-hidden p-5">
      <div className="-mx-5 -mt-5 mb-5 h-1" style={{ backgroundColor: driver.team?.color || "#64748b" }} />
      <div className="flex items-start justify-between gap-3">
        <DriverBadge code={driver.code} color={driver.team?.color} />
        <div className="font-mono text-sm text-slate-500">#{driver.number ?? "--"}</div>
      </div>
      <div className="mt-3 text-xl font-black text-white">{driver.full_name}</div>
      <div className="mt-4">
        {driver.team ? (
          <TeamColorPill name={driver.team.name} color={driver.team.color} />
        ) : (
          <span className="text-xs text-slate-500">No team listed</span>
        )}
      </div>
      <div className="mt-5 grid grid-cols-3 gap-2 border-t border-line/70 pt-4 text-center">
        <Stat label="Finish" value={card.finish === null ? (card.classification ?? "--") : `P${card.finish}`} />
        <Stat label="Median pace" value={formatMs(card.medianLapMs)} />
        <Stat label="Ideal" value={formatMs(card.idealLapMs)} />
      </div>
    </div>
  );
}

/** The teams of one session: who drove, and what the two of them did in it. */
export function TeamsSummary({ view }: { view: SessionView }) {
  const { artifact, retry } = usePublishedArtifact(view, readField);
  return (
    <ArtifactPanel name="teams" artifact={artifact} onRetry={retry}>
      {(field) => {
        const cards = teamCards(field);
        return cards.length === 0 ? (
          <EmptyState title="No teams" detail="This session was published without a driver list." />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {cards.map((card) => (
              <TeamCardView key={card.id} card={card} />
            ))}
          </div>
        );
      }}
    </ArtifactPanel>
  );
}

function TeamCardView({ card }: { card: TeamCard }) {
  return (
    <div className="surface p-5">
      <div className="h-2 rounded" style={{ backgroundColor: card.color || "#64748b" }} />
      <div className="mt-4 text-xl font-black text-white">{card.name}</div>
      <div className="mt-4 space-y-2">
        {card.drivers.map((driver) => (
          <div key={driver.code} className="flex items-center gap-3">
            <DriverBadge code={driver.code} color={card.color} />
            <span className="truncate text-sm text-slate-400">{driver.full_name}</span>
          </div>
        ))}
      </div>
      <div className="mt-5 grid grid-cols-3 gap-2 border-t border-line/70 pt-4 text-center">
        <Stat label="Points here" value={card.points === null ? "--" : String(card.points)} />
        <Stat label="Best finish" value={card.bestFinish === null ? "--" : `P${card.bestFinish}`} />
        <Stat label="Pace laps" value={card.paceLaps === null ? "--" : String(card.paceLaps)} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">{label}</div>
      <div className="mt-1 truncate font-mono text-xs font-bold text-slate-200" title={value}>
        {value}
      </div>
    </div>
  );
}
