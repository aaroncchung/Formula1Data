import { DataTable } from "@/components/data-table/DataTable";
import { CompoundBadge, DriverBadge } from "@/components/session/Badges";
import { formatDelta, formatMs } from "@/lib/format";
import type { PitStop, StrategyResult } from "@/types/domain";

export function StrategyAnalysis({ strategy, pitStops }: { strategy: StrategyResult | null; pitStops: PitStop[] }) {
  const usage = Object.entries(strategy?.compound_usage || {}).sort((a, b) => b[1] - a[1]);
  const estimates = strategy?.undercut_overcut || [];
  const stops = strategy?.pit_stops?.length ? strategy.pit_stops : pitStops;
  const drivers = new Set(stops.map((stop) => stop.driver_code)).size;
  const recordedDurations = stops.filter((stop) => stop.duration_ms != null);
  const fastestStop = recordedDurations.length
    ? recordedDurations.reduce((best, stop) => Number(stop.duration_ms) < Number(best.duration_ms) ? stop : best)
    : null;

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StrategyMetric label="Pit events" value={stops.length} detail={`${drivers} drivers`} />
        <StrategyMetric label="Compounds used" value={usage.length || "--"} detail={usage.map(([compound]) => compound).join(" · ") || "Not available"} />
        <StrategyMetric label="Fastest pit-lane time" value={fastestStop ? formatMs(fastestStop.duration_ms) : "Not recorded"} detail={fastestStop?.driver_code || "Pit-in/out timing unavailable"} />
        <StrategyMetric label="Estimated pit loss" value={formatMs(strategy?.pit_loss_estimate_ms)} detail="Model estimate" />
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

      <div>
        <div className="mb-3">
          <h3 className="font-bold text-white">Pit stop log</h3>
          <p className="mt-1 text-sm text-slate-500">Every detected pit-in event. Recorded time is total pit-lane transit from pit-in to pit-out, not stationary service time.</p>
        </div>
        <DataTable
          rows={stops}
          emptyText="No pit events detected."
          columns={[
            { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} /> },
            { key: "lap", header: "Stop lap", align: "right", render: (row) => row.lap_number },
            { key: "duration", header: "Pit-lane time", align: "right", render: (row) => row.duration_ms == null ? <span className="text-slate-600">Not recorded</span> : formatMs(row.duration_ms) },
            { key: "time", header: "Local time", align: "right", render: (row) => row.local_time || <span className="text-slate-600">--</span> }
          ]}
        />
      </div>

      {estimates.length ? (
        <div>
          <div className="mb-3">
            <h3 className="font-bold text-white">Post-stop pace change</h3>
            <p className="mt-1 text-sm text-slate-500">First clean lap after the stop compared with the driver&apos;s surrounding laps; negative is quicker.</p>
          </div>
          <DataTable
            rows={estimates}
            columns={[
              { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} /> },
              { key: "lap", header: "Stop lap", align: "right", render: (row) => row.stop_lap },
              { key: "gain", header: "Pace change", align: "right", render: (row) => <span className={Number(row.first_clean_lap_gain_ms) < 0 ? "text-aqua" : "text-amber"}>{formatDelta(row.first_clean_lap_gain_ms)}</span> }
            ]}
          />
        </div>
      ) : null}

      {strategy?.caveats.length ? <p className="rounded-md border border-amber/20 bg-amber/5 p-3 text-xs leading-5 text-slate-400">{strategy.caveats.join(" ")}</p> : null}
    </div>
  );
}

function StrategyMetric({ label, value, detail }: { label: string; value: string | number; detail: string }) {
  return (
    <div className="rounded-md border border-line/70 bg-carbon/45 p-3">
      <div className="eyebrow">{label}</div>
      <div className="mt-2 text-xl font-black text-white">{value}</div>
      <div className="mt-1 truncate text-xs text-slate-500" title={detail}>{detail}</div>
    </div>
  );
}
