import { DataTable } from "@/components/data-table/DataTable";
import { CompoundBadge, DriverBadge } from "@/components/session/Badges";
import { formatMs } from "@/lib/format";
import { formatElapsed, formatSessionClock } from "@/lib/pandas-time";
import {
  paceChange,
  pitLaneSummary,
  pitLossExclusionLabel,
  pitLossSummary,
  pitStopLog,
  type PitLaneSummary,
  type PitLossSummary,
  type PitStopLogRow
} from "@/lib/strategy-view";
import type { PitStop, StrategyEstimate, StrategyResult } from "@/types/domain";

/**
 * Compound usage, the pit stops and the pace change across each driver's
 * first stop. `strategy` is null for a session without the analysis; the pit
 * stops are then shown from the stop list alone.
 */
export function StrategyAnalysis({ strategy, pitStops }: { strategy: StrategyResult | null; pitStops: PitStop[] }) {
  const usage = Object.entries(strategy?.compound_usage || {}).sort((a, b) => b[1] - a[1]);
  const estimates = strategy?.undercut_overcut || [];
  const stops = pitStopLog(strategy, pitStops);
  const drivers = new Set(stops.map((stop) => stop.driver_code)).size;
  const caveats = strategy?.caveats ?? [];

  return (
    <div className="space-y-5">
      {strategy ? null : (
        <p className="rounded-md border border-line/70 bg-carbon/35 p-3 text-sm text-slate-400">
          This session has no strategy analysis, so compound usage, pit loss and the pace change across a stop are not
          shown. The pit stops below come from the stop list.
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StrategyMetric label="Pit stops" value={stops.length} detail={`${drivers} ${drivers === 1 ? "driver" : "drivers"}`} />
        <StrategyMetric label="Compounds used" value={usage.length || "--"} detail={usage.map(([compound]) => compound).join(" · ") || "Not available"} />
        <PitLaneMetric summary={pitLaneSummary(strategy, pitStops)} />
        <PitLossMetric summary={pitLossSummary(strategy)} />
      </div>

      {usage.length ? (
        <section className="rounded-md border border-line/70 bg-carbon/35 p-4">
          <div className="eyebrow">Compound usage</div>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {usage.map(([compound, count]) => (
              <div key={compound} className="flex items-center justify-between rounded-md border border-line/70 bg-white/[0.025] p-3">
                <CompoundBadge compound={compound} />
                <div className="text-right">
                  <div className="font-mono text-lg font-black text-white">{count}</div>
                  <div className="text-[11px] text-slate-500">stints</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <PitStopLog stops={stops} />
      {estimates.length ? <PaceChangeTable estimates={estimates} /> : null}

      {caveats.length ? <p className="rounded-md border border-amber/20 bg-amber/5 p-3 text-xs leading-5 text-slate-400">{caveats.join(" ")}</p> : null}
    </div>
  );
}

/** Pit-lane transit, labelled as that: entry to exit, with the stationary time in it. */
function PitLaneMetric({ summary }: { summary: PitLaneSummary }) {
  if (summary.median_ms === null) {
    return <StrategyMetric label="Pit-lane time (median)" value="Not recorded" detail="No stop has both a pit-entry and a pit-exit time" />;
  }
  return (
    <StrategyMetric
      label="Pit-lane time (median)"
      value={seconds(summary.median_ms)}
      detail={`Entry to exit · fastest ${seconds(summary.fastest_ms)}, slowest ${seconds(summary.slowest_ms)} · ${summary.timedStopCount} of ${summary.stopCount} stops timed`}
    />
  );
}

/** What a stop costs against staying out. A different quantity from pit-lane time, and often absent. */
function PitLossMetric({ summary }: { summary: PitLossSummary }) {
  const label = "Pit loss (estimate)";
  switch (summary.status) {
    case "estimated":
      return (
        <StrategyMetric
          label={label}
          value={seconds(summary.estimate_ms)}
          detail={`Against staying out · median of ${summary.qualifyingStopCount} of ${summary.stopCount} stops${
            summary.spread_ms === null ? "" : ` · spread ${seconds(summary.spread_ms)}`
          }`}
        />
      );
    case "too_few_stops":
      return (
        <StrategyMetric
          label={label}
          value="Not estimated"
          detail={`${summary.qualifyingStopCount} of ${summary.stopCount} stops qualify${
            summary.minimumStopCount === null ? "" : `; ${summary.minimumStopCount} are needed`
          }`}
        />
      );
    case "no_stops":
      return <StrategyMetric label={label} value="Not estimated" detail="No pit stops were recorded" />;
    case "not_published":
      return <StrategyMetric label={label} value="Not published" detail="This session's data has no pit-loss estimate" />;
  }
}

function PitStopLog({ stops }: { stops: PitStopLogRow[] }) {
  // Without a per-stop estimate the column would be a column of dashes.
  const hasPitLoss = stops.some((stop) => stop.pitLoss !== null);
  return (
    <div>
      <div className="mb-3">
        <h3 className="font-bold text-white">Pit stop log</h3>
        <p className="mt-1 text-sm text-slate-500">
          Every detected stop. Pit-lane time is the transit from pit entry to pit exit, stationary time included.
          {hasPitLoss
            ? " Pit loss is what the stop cost against staying out: in-lap plus out-lap, minus two laps at the driver's pace around the stop."
            : ""}
        </p>
      </div>
      <DataTable
        rows={stops}
        emptyText="No pit stops detected."
        columns={[
          { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} /> },
          { key: "lap", header: "Stop lap", align: "right", render: (row) => row.lap_number },
          { key: "entry", header: "Pit entry (session clock)", align: "right", render: (row) => <span className="font-mono">{formatSessionClock(row.entry_clock_ms)}</span> },
          { key: "duration", header: "Pit-lane time", align: "right", render: (row) => row.duration_ms === null ? <span className="text-slate-600">Not recorded</span> : seconds(row.duration_ms) },
          ...(hasPitLoss
            ? [{ key: "loss", header: "Pit loss", align: "right" as const, render: (row: PitStopLogRow) => <StopPitLossCell stop={row} /> }]
            : [])
        ]}
      />
    </div>
  );
}

function StopPitLossCell({ stop }: { stop: PitStopLogRow }) {
  if (stop.pitLoss === null) {
    return <span className="text-slate-600">--</span>;
  }
  if (stop.pitLoss.status === "estimated") {
    return <>{seconds(stop.pitLoss.pit_loss_ms)}</>;
  }
  return <span className="text-xs text-slate-500">Not estimated: {pitLossExclusionLabel(stop.pitLoss.reason)}</span>;
}

function PaceChangeTable({ estimates }: { estimates: StrategyEstimate[] }) {
  // The two laps compared are named only by a generation that carries them.
  const namesLaps = estimates.some((row) => row.before_lap_number != null || row.after_lap_number != null);
  return (
    <div>
      <div className="mb-3">
        <h3 className="font-bold text-white">Pace change across the first stop</h3>
        <p className="mt-1 text-sm text-slate-500">
          The driver&apos;s last clean lap before the stop against the first one after it. Quicker means quicker on
          the new tyres. Not adjusted for fuel, traffic or track evolution.
        </p>
      </div>
      <DataTable
        rows={estimates}
        columns={[
          { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} /> },
          { key: "lap", header: "Stop lap", align: "right", render: (row) => row.stop_lap },
          ...(namesLaps
            ? [
                { key: "before", header: "Lap before", align: "right" as const, render: (row: StrategyEstimate) => <ComparedLap lap={row.before_lap_number} time={row.before_lap_ms} /> },
                { key: "after", header: "Lap after", align: "right" as const, render: (row: StrategyEstimate) => <ComparedLap lap={row.after_lap_number} time={row.after_lap_ms} /> }
              ]
            : []),
          { key: "change", header: "Pace change", align: "right", render: (row) => <PaceChangeCell estimate={row} /> }
        ]}
      />
    </div>
  );
}

function ComparedLap({ lap, time }: { lap?: number | null; time?: number | null }) {
  if (lap == null) {
    return <span className="text-slate-600">--</span>;
  }
  return (
    <span className="font-mono">
      <span className="text-slate-500">L{lap}</span> {formatMs(time)}
    </span>
  );
}

function PaceChangeCell({ estimate }: { estimate: StrategyEstimate }) {
  const change = paceChange(estimate);
  if (change.direction === "none") {
    // The row says why it has no value; a bare dash would hide that there is a reason.
    return <span className="inline-block max-w-xs text-left text-xs text-slate-500">{estimate.caveat || "No value"}</span>;
  }
  const tone = change.direction === "quicker" ? "text-aqua" : change.direction === "slower" ? "text-amber" : "text-slate-300";
  return <span className={`font-mono ${tone}`}>{change.text}</span>;
}

function StrategyMetric({ label, value, detail }: { label: string; value: string | number; detail: string }) {
  return (
    <div className="rounded-md border border-line/70 bg-carbon/45 p-3">
      <div className="eyebrow">{label}</div>
      <div className="mt-2 text-xl font-black text-white">{value}</div>
      <div className="mt-1 text-xs leading-4 text-slate-500">{detail}</div>
    </div>
  );
}

function seconds(ms: number | null): string {
  return formatElapsed(ms);
}
