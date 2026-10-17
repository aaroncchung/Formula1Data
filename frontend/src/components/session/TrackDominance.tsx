import { DriverMark } from "@/components/charts/DriverMark";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { CornerMarks } from "@/components/session/CornerMarks";
import { circuitLayout, layoutNote, trackMap } from "@/lib/circuit-layout";
import { driverStyle, teamDriverStyles } from "@/lib/driver-style";
import type { DriverStyles } from "@/lib/driver-style";
import { minisectorTally } from "@/lib/performance-view";
import type { Corners, Driver, TrackDominance as TrackDominanceResult } from "@/lib/published/types";
import type { Point, Viewport } from "@/lib/track-map";

/** The dash of the second team-mate, scaled up for the thick line of the track map. */
const TRACK_DASH = "12 7";
// The padding leaves room for a corner's label off the outside of the track.
const DOMINANCE_VIEWPORT: Viewport = { width: 600, height: 400, padding: 36 };
const CORNER_RADIUS = 8;
const CORNER_LABEL_DISTANCE = 20;

/**
 * The circuit, each minisector in the colour of the driver who was quickest
 * through it, with the count beside it. `corners` is the circuit's own corner
 * map, or null when the session has none: where it fits the track, the map is
 * turned the way F1 draws the circuit and its corners are numbered.
 */
export function TrackDominance({
  result,
  drivers,
  corners
}: {
  result: TrackDominanceResult;
  drivers: ReadonlyArray<Driver>;
  corners: Corners | null;
}) {
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
  const tally = minisectorTally(result);
  const total = result.minisectors.length;
  const excluded = result.excluded_drivers;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_220px]">
      {/* Without positions there is no map, and the count beside it still
          stands: who was quickest through a minisector is from its times. */}
      <DominanceMap sectors={sectors} corners={corners} styles={styles} />
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

type PlacedSector = { index: number; winner: string; midpoint: Point };

/** The circuit in the winners' colours, or why it cannot be drawn. */
function DominanceMap({
  sectors,
  corners,
  styles
}: {
  sectors: ReadonlyArray<PlacedSector>;
  corners: Corners | null;
  styles: DriverStyles;
}) {
  const layout = circuitLayout(corners);
  const map = sectors.length < 2 ? null : trackMap(sectors.map((sector) => sector.midpoint), layout, DOMINANCE_VIEWPORT, CORNER_LABEL_DISTANCE);
  if (!map) {
    return (
      <EmptyState
        title="Track map unavailable"
        detail="The minisectors have no positions on the track to draw them at. Who was quickest through each is counted all the same."
      />
    );
  }
  const placed = sectors.map((sector) => map.place(sector.midpoint));
  const note = layoutNote(layout);
  return (
    <div>
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
        <CornerMarks corners={map.corners} radius={CORNER_RADIUS} />
      </svg>
      {map.corners.length ? (
        <p className="mt-2 text-xs text-slate-500">Numbered discs are the circuit&apos;s official corners.</p>
      ) : null}
      {note ? <p className="mt-2 text-xs text-slate-500">{note}</p> : null}
    </div>
  );
}
