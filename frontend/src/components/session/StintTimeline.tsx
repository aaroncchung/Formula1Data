import { COMPOUND_COLORS } from "@/lib/constants";
import type { Stint } from "@/types/domain";

export function StintTimeline({ stints }: { stints: Stint[] }) {
  const maxLap = Math.max(...stints.map((stint) => stint.end_lap), 1);
  return (
    <div className="space-y-3">
      {stints.map((stint) => {
        const left = ((stint.start_lap - 1) / maxLap) * 100;
        const width = Math.max(((stint.end_lap - stint.start_lap + 1) / maxLap) * 100, 6);
        const color = COMPOUND_COLORS[stint.compound] || "#94a3b8";
        return (
          <div key={`${stint.driver_code}-${stint.stint}`} className="grid grid-cols-[54px_1fr] items-center gap-3">
            <div className="font-mono text-sm font-bold text-white">{stint.driver_code}</div>
            <div className="relative h-8 rounded bg-white/[0.04]">
              <div
                className="absolute top-1 h-6 rounded px-2 text-xs font-bold leading-6 text-carbon"
                style={{ left: `${left}%`, width: `${width}%`, backgroundColor: color }}
              >
                S{stint.stint} {stint.compound}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

