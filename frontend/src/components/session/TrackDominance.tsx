import { DriverMark } from "@/components/charts/DriverMark";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { driverStyle, teamDriverStyles } from "@/lib/driver-style";
import { minisectorTally } from "@/lib/performance-view";
import { boundsOf, fitBounds, project, type Viewport } from "@/lib/track-map";
import type { Driver, TrackDominance as TrackDominanceResult } from "@/lib/published/types";

/** The dash of the second team-mate, scaled up for the thick line of the track map. */
const TRACK_DASH = "12 7";
const DOMINANCE_VIEWPORT: Viewport = { width: 600, height: 400, padding: 25 };

/**
 * The circuit, each minisector in the colour of the driver who was quickest
 * through it, with the count beside it.
 */
export function TrackDominance({ result, drivers }: { result: TrackDominanceResult; drivers: ReadonlyArray<Driver> }) {
  // The map identifies a driver by the line alone, so team-mates need the
  // shared solid/dashed styles here, not just the team colour.
  const styles = teamDriverStyles(drivers);
  // A minisector has no midpoint where the representative lap has no
  // position there, and no winner where no driver has a time through it.
  const sectors = result.minisectors.flatMap((sector) => {
    const { x, y } = sector.midpoint;
    return x === null || y === null || !sector.winner_driver_code
      ? []
      : [{ index: sector.index, winner: sector.winner_driver_code, midpoint: { x, y } }];
  });
  const midpoints = sectors.map((sector) => sector.midpoint);
  const bounds = sectors.length < 2 ? null : boundsOf(midpoints);
  if (!bounds) return <EmptyState title="Track map unavailable" detail="The minisector artifact has no usable coordinates." />;
  const projection = fitBounds(bounds, DOMINANCE_VIEWPORT);
  const placed = midpoints.map((midpoint) => project(projection, midpoint));
  const tally = minisectorTally(result);
  const total = result.minisectors.length;
  const excluded = result.excluded_drivers;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_220px]">
      <svg viewBox="0 0 600 400" className="min-h-[280px] w-full rounded-md border border-line/70 bg-carbon/50 p-3" role="img" aria-label="Track dominance by driver">
        {sectors.slice(1).map((sector, index) => {
          const from = placed[index];
          const to = placed[index + 1];
          const style = driverStyle(styles, sector.winner);
          return (
            <line
              key={sector.index}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={style.color}
              strokeWidth="10"
              strokeLinecap={style.dash ? "butt" : "round"}
              strokeDasharray={style.dash ? TRACK_DASH : undefined}
            />
          );
        })}
      </svg>
      <div className="space-y-2">
        <div className="eyebrow mb-3">Minisectors won</div>
        {tally.map((entry) => (
          <div key={entry.driver} className="flex items-center justify-between rounded-md border border-line/70 bg-carbon/40 p-3">
            <span className="inline-flex items-center gap-2 font-mono font-semibold text-white">
              <DriverMark style={driverStyle(styles, entry.driver)} mark="line" />
              {entry.driver}
            </span>
            <span className="font-mono text-sm font-bold text-white">
              {entry.won}
              {/* A driver with a hole in their telemetry was not in the running everywhere. */}
              {entry.timed < total ? <span className="ml-1 text-xs font-normal text-slate-500">of {entry.timed} timed</span> : null}
            </span>
          </div>
        ))}
        {excluded.length ? (
          <p className="pt-1 text-xs leading-5 text-slate-500">
            Not compared, having no clean lap with complete telemetry: {excluded.join(", ")}.
          </p>
        ) : null}
      </div>
    </div>
  );
}
