import { groupByDriver } from "@/lib/chart-utils";
import { formatElapsed } from "@/lib/durations";
import type { PitStop } from "@/lib/published/types";
import { pitEntryKind } from "@/lib/strategy-view";

/**
 * `lastLap` is the last lap of the session, when the caller knows it. The
 * axis then runs to the end of the session, like the stint timeline drawn
 * above it. Without it the axis ends at the last stop, which puts that stop
 * at the right-hand edge as if it were made on the final lap.
 */
export function PitStopTimeline({ stops, lastLap = 0 }: { stops: ReadonlyArray<PitStop>; lastLap?: number }) {
  const maxLap = Math.max(lastLap, ...stops.map((stop) => stop.lap_number), 1);
  const drivers = groupByDriver(stops);
  if (!drivers.length) return <div className="rounded-md border border-dashed border-line p-6 text-center text-sm text-slate-500">No pit events detected.</div>;
  return (
    <div className="space-y-3">
      {drivers.map(([driver, driverStops]) => (
        <div key={driver} className="grid grid-cols-[54px_1fr] items-center gap-3">
          <div className="font-mono text-sm font-bold text-white">{driver}</div>
          <div className="relative h-8 rounded-md bg-white/[0.04]">
            <div className="absolute inset-x-2 top-1/2 h-px bg-line" />
            {driverStops.map((stop, index) => (
              <div
                key={`${stop.driver_code}-${stop.lap_number}-${index}`}
                className={`absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 ${
                  // A car waiting out a red flag in the pit lane, and a car that
                  // went through without stopping, are marked apart from a car making a stop.
                  stop.under_red_flag
                    ? "border-carbon bg-redline shadow-[0_0_0_3px_rgba(243,61,61,0.15)]"
                    : pitEntryKind(stop) === "passage"
                      ? "border-slate-500 bg-carbon"
                      : "border-carbon bg-aqua shadow-[0_0_0_3px_rgba(45,224,200,0.15)]"
                }`}
                style={{ left: `${Math.max(1, (stop.lap_number / maxLap) * 100)}%` }}
                title={stopTitle(stop)}
              />
            ))}
          </div>
        </div>
      ))}
      <div className="grid grid-cols-[54px_1fr] gap-3 pt-1 text-[10px] text-slate-600"><span /><div className="flex justify-between"><span>Lap 1</span><span>Lap {maxLap}</span></div></div>
      <p className="text-xs text-slate-500">
        A marker is the lap a car came into the pits on. Hover for how long it stood still and how long it was in the pit lane, where those were recorded.
        {stops.some((stop) => stop.under_red_flag) ? " A red marker is a car that was in the pit lane when the session was red-flagged." : ""}
        {stops.some((stop) => pitEntryKind(stop) === "passage") ? " A hollow marker is a car that went through the pit lane without stopping." : ""}
      </p>
    </div>
  );
}

/** What is known of one stop, each figure under its own name. */
function stopTitle(stop: PitStop): string {
  const parts = [`Lap ${stop.lap_number}`];
  if (stop.under_red_flag) {
    // The time in the lane is how long the session was stopped, not how long a stop took.
    parts.push(
      stop.duration_ms === null
        ? "in the pit lane through a red flag"
        : `waited ${formatElapsed(stop.duration_ms)} in the pit lane through a red flag`
    );
    return parts.join(" · ");
  }
  if (pitEntryKind(stop) === "passage") {
    parts.push("went through without stopping");
  }
  if (stop.stationary_ms !== null) {
    parts.push(`stationary ${formatElapsed(stop.stationary_ms)}`);
  }
  parts.push(stop.duration_ms === null ? "pit entry to exit not recorded" : `pit entry to exit ${formatElapsed(stop.duration_ms)}`);
  return parts.join(" · ");
}
