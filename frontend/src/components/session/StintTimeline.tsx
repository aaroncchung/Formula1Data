import { COMPOUND_COLORS } from "@/lib/constants";
import type { Stint } from "@/types/domain";

export function StintTimeline({ stints }: { stints: Stint[] }) {
  const maxLap = Math.max(...stints.map((stint) => stint.end_lap), 1);
  const drivers = Array.from(stints.reduce((groups, stint) => {
    const rows = groups.get(stint.driver_code) || [];
    rows.push(stint);
    groups.set(stint.driver_code, rows);
    return groups;
  }, new Map<string, Stint[]>()).entries());
  return (
    <div className="space-y-3">
      {drivers.map(([driver, driverStints]) => (
          <div key={driver} className="grid grid-cols-[54px_1fr] items-center gap-3">
            <div className="font-mono text-sm font-bold text-white">{driver}</div>
            <div className="relative h-9 overflow-hidden rounded-md bg-white/[0.04]">
              {driverStints.map((stint) => {
                const left = ((stint.start_lap - 1) / maxLap) * 100;
                const width = ((stint.end_lap - stint.start_lap + 1) / maxLap) * 100;
                const color = COMPOUND_COLORS[stint.compound] || "#94a3b8";
                return (
                  <div
                    key={stint.stint}
                    className="absolute top-1 flex h-7 min-w-[3px] items-center overflow-hidden border-r border-carbon/50 px-1.5 text-[10px] font-black text-carbon"
                    style={{ left: `${left}%`, width: `${width}%`, backgroundColor: color }}
                    title={`Stint ${stint.stint}: ${stint.compound}, laps ${stint.start_lap}–${stint.end_lap}`}
                  >
                    <span className="truncate">{stint.compound.slice(0, 1)} · {stint.lap_count}</span>
                  </div>
                );
              })}
            </div>
          </div>
      ))}
      <div className="grid grid-cols-[54px_1fr] gap-3 pt-1 text-[10px] text-slate-600">
        <span />
        <div className="flex justify-between"><span>Lap 1</span><span>Lap {maxLap}</span></div>
      </div>
    </div>
  );
}

