import { groupByDriver } from "@/lib/chart-utils";
import { formatMs } from "@/lib/format";
import type { PitStop } from "@/types/domain";

export function PitStopTimeline({ stops }: { stops: PitStop[] }) {
  const maxLap = Math.max(...stops.map((stop) => stop.lap_number), 1);
  const drivers = groupByDriver(stops);
  if (!drivers.length) return <div className="rounded-md border border-dashed border-line p-6 text-center text-sm text-slate-500">No pit events detected.</div>;
  return (
    <div className="space-y-3">
      {drivers.map(([driver, driverStops]) => (
        <div key={driver} className="grid grid-cols-[54px_1fr] items-center gap-3">
          <div className="font-mono text-sm font-bold text-white">{driver}</div>
          <div className="relative h-8 rounded-md bg-white/[0.04]">
            <div className="absolute inset-x-2 top-1/2 h-px bg-line" />
            {driverStops.map((stop) => (
              <div
                key={`${stop.driver_code}-${stop.lap_number}`}
                className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-carbon bg-aqua shadow-[0_0_0_3px_rgba(45,224,200,0.15)]"
                style={{ left: `${Math.max(1, (stop.lap_number / maxLap) * 100)}%` }}
                title={`Lap ${stop.lap_number} · Pit-lane transit ${stop.duration_ms == null ? "not recorded" : formatMs(stop.duration_ms)}`}
              />
            ))}
          </div>
        </div>
      ))}
      <div className="grid grid-cols-[54px_1fr] gap-3 pt-1 text-[10px] text-slate-600"><span /><div className="flex justify-between"><span>Lap 1</span><span>Lap {maxLap}</span></div></div>
      <p className="text-xs text-slate-500">Markers show detected pit-in laps. Hover for pit-lane transit time when the source provides pit-in and pit-out timestamps.</p>
    </div>
  );
}
