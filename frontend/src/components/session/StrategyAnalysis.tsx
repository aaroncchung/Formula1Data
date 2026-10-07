import { DataTable } from "@/components/data-table/DataTable";
import { CompoundBadge, DriverBadge } from "@/components/session/Badges";
import { formatElapsed, formatSessionClock } from "@/lib/durations";
import { formatMs } from "@/lib/format";
import type { PaceChangeAcrossStop, PitStop, Strategy } from "@/lib/published/types";
import {
  paceChange,
  pitLaneSummary,
  pitLossExclusionLabel,
  pitLossSummary,
  pitStopLog,
  stationarySummary,
  type PitLaneSummary,
  type PitLossSummary,
  type PitStopLogRow,
  type StationarySummary
} from "@/lib/strategy-view";

/**
 * Compound usage, the pit stops and the pace change across each driver's
 * first stop. `strategy` is null for a session without the analysis; the pit
 * stops are then shown from the stop list alone.
 */
export function StrategyAnalysis({ strategy, pitStops }: { strategy: Strategy | null; pitStops: ReadonlyArray<PitStop> }) {
  const usage = Object.entries(strategy?.compound_usage ?? {}).sort((a, b) => b[1] - a[1]);
  const estimates = strategy?.undercut_overcut ?? [];
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
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StrategyMetric label="Pit stops" value={stops.length} detail={`${drivers} ${drivers === 1 ? "driver" : "drivers"}`} />
        <StrategyMetric label="Compounds used" value={usage.length || "--"} detail={usage.map(([compound]) => compound).join(" · ") || "Not available"} />
        <StationaryMetric summary={stationarySummary(pitStops)} />
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

/** How long the cars stood still, which is what is usually meant by the length of a pit stop. */
function StationaryMetric({ summary }: { summary: StationarySummary }) {
  const label = "Stationary time (median)";
  if (summary.median_ms === null || summary.fastest === null) {
    return <StrategyMetric label={label} value="Not reported" detail="F1's pit-stop feed has no stop of this session" />;
  }
  const { fastest } = summary;
  return (
    <StrategyMetric
      label={label}
      value={seconds(summary.median_ms)}
      detail={`Car standing still · fastest ${seconds(fastest.stationary_ms)}, ${fastest.driver_code} on lap ${fastest.lap_number} · ${summary.timedStopCount} of ${summary.stopCount} stops reported`}
    />
  );
}

/** Pit entry to pit exit, labelled as that: the stationary time is inside it. */
function PitLaneMetric({ summary }: { summary: PitLaneSummary }) {
  const label = "Entry to exit (median)";
  if (summary.median_ms === null) {
    return <StrategyMetric label={label} value="Not recorded" detail="No stop has both a pit-entry and a pit-exit time" />;
  }
  return (
    <StrategyMetric
      label={label}
      value={seconds(summary.median_ms)}
      detail={`Through the pit lane · fastest ${seconds(summary.fastest_ms)}, slowest ${seconds(summary.slowest_ms)} · ${summary.timedStopCount} of ${summary.stopCount} stops timed${redFlagNote(summary.redFlagCount)}`}
    />
  );
}

/** Why some entries to the pit lane are in none of the figures. */
function redFlagNote(count: number): string {
  if (count === 0) {
    return "";
  }
  return ` · ${count} ${count === 1 ? "was a wait" : "were waits"} through a red flag, left out`;
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
          detail={`${summary.qualifyingStopCount} of ${summary.stopCount} stops qualify; ${summary.minimumStopCount} are needed`}
        />
      );
    case "no_stops":
      return <StrategyMetric label={label} value="Not estimated" detail="No pit stops were recorded" />;
    case "not_published":
      return <StrategyMetric label={label} value="Not published" detail="This session's data has no pit-loss estimate" />;
  }
}

function PitStopLog({ stops }: { stops: PitStopLogRow[] }) {
  // A column nothing would fill is left out: F1's feed can be missing for a
  // whole session, and so can the strategy analysis.
  const hasFeed = stops.some((stop) => stop.stationary_ms !== null || stop.pit_lane_ms !== null);
  const hasPitLoss = stops.some((stop) => stop.pitLoss !== null);
  const reported = stops.filter((stop) => stop.stationary_ms !== null).length;
  const redFlagged = stops.filter((stop) => stop.under_red_flag).length;
  return (
    <div>
      <div className="mb-3">
        <h3 className="font-bold text-white">Pit stop log</h3>
        <p className="mt-1 text-sm text-slate-500">
          Every entry to the pit lane.{" "}
          {hasFeed
            ? `Stationary and pit-lane times are F1's own figures, which its pit-stop feed gives for ${reported} of these ${stops.length} stops. `
            : stops.length
              ? "F1's pit-stop feed reports none of these stops, so there are no stationary times. "
              : ""}
          Entry to exit is the time between the timing&apos;s pit-entry and pit-exit, stationary time included.
          {redFlagged > 0
            ? ` ${redFlagged} of these ${redFlagged === 1 ? "was a car" : "were cars"} in the pit lane when the session was red-flagged: what is timed there is the wait for the restart, and it is in none of the figures above.`
            : ""}
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
          {
            key: "lap",
            header: "Stop lap",
            align: "right",
            render: (row) => (
              <>
                {row.under_red_flag ? <RedFlagMark /> : null}
                {row.lap_number}
              </>
            )
          },
          { key: "entry", header: "Pit entry (session clock)", align: "right", render: (row) => <span className="font-mono">{formatSessionClock(row.entry_time_ms)}</span> },
          ...(hasFeed
            ? [
                { key: "stationary", header: "Stationary", align: "right" as const, render: (row: PitStopLogRow) => <FeedTime ms={row.stationary_ms} /> },
                { key: "lane", header: "Pit lane", align: "right" as const, render: (row: PitStopLogRow) => <FeedTime ms={row.pit_lane_ms} /> }
              ]
            : []),
          { key: "duration", header: "Entry to exit", align: "right", render: (row) => row.duration_ms === null ? <span className="text-slate-600" title="The car did not come back out of the pit lane">Not recorded</span> : seconds(row.duration_ms) },
          ...(hasPitLoss
            ? [{ key: "loss", header: "Pit loss", align: "right" as const, render: (row: PitStopLogRow) => <StopPitLossCell stop={row} /> }]
            : [])
        ]}
      />
    </div>
  );
}

/** Beside the lap of a car that sat out a red flag in the pit lane, so its long times are read as the wait they are. */
function RedFlagMark() {
  return (
    <span
      className="mr-2 rounded border border-redline/40 bg-redline/10 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-redline"
      title="The session was red-flagged while this car was in the pit lane. Its times are a wait for the restart, not a pit stop."
    >
      Red flag
    </span>
  );
}

/** A figure from F1's pit-stop feed, or a dash for a stop the feed does not report. */
function FeedTime({ ms }: { ms: number | null }) {
  return ms === null ? (
    <span className="text-slate-600" title="F1's pit-stop feed does not report this stop">
      --
    </span>
  ) : (
    <span className="font-mono">{seconds(ms)}</span>
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

function PaceChangeTable({ estimates }: { estimates: ReadonlyArray<PaceChangeAcrossStop> }) {
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
          { key: "before", header: "Lap before", align: "right", render: (row) => <ComparedLap lap={row.before_lap_number} time={row.before_lap_ms} /> },
          { key: "after", header: "Lap after", align: "right", render: (row) => <ComparedLap lap={row.after_lap_number} time={row.after_lap_ms} /> },
          { key: "change", header: "Pace change", align: "right", render: (row) => <PaceChangeCell estimate={row} /> }
        ]}
      />
    </div>
  );
}

function ComparedLap({ lap, time }: { lap: number | null; time: number | null }) {
  if (lap === null) {
    return <span className="text-slate-600">--</span>;
  }
  return (
    <span className="font-mono">
      <span className="text-slate-500">L{lap}</span> {formatMs(time)}
    </span>
  );
}

function PaceChangeCell({ estimate }: { estimate: PaceChangeAcrossStop }) {
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
