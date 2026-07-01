import { formatMs } from "@/lib/format";
import type { PitStop } from "@/types/domain";

export function PitStopTimeline({ stops }: { stops: PitStop[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {stops.map((stop) => (
        <div key={`${stop.driver_code}-${stop.lap_number}`} className="rounded border border-line bg-white/[0.03] p-3">
          <div className="font-mono text-lg font-black text-white">{stop.driver_code}</div>
          <div className="mt-1 text-sm text-slate-400">Lap {stop.lap_number}</div>
          <div className="mt-2 text-xl font-black text-aqua">{formatMs(stop.duration_ms)}</div>
        </div>
      ))}
    </div>
  );
}

