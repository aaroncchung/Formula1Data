import type { PositionReplayFrame } from "@/types/domain";

/**
 * Geometry for drawing positions on a circuit.
 *
 * A track map has to do two things a chart axis does not do by default: use
 * one scale for both axes, or the circuit is stretched, and keep that scale
 * fixed while the cars move, or the circuit appears to move instead. So the
 * extent is taken once from every point that will ever be drawn, and one
 * projection made from it is used for all of them.
 */

export type Point = { x: number; y: number };

export type Bounds = { minX: number; maxX: number; minY: number; maxY: number };

/** The drawing area in its own units, with a margin kept clear on every side. */
export type Viewport = { width: number; height: number; padding: number };

export type Projection = {
  /** Viewport units per data unit, the same on both axes. */
  scale: number;
  /** The data point that lands on the centre of the viewport. */
  center: Point;
  viewport: Viewport;
};

/** A coordinate as a finite number, or null when the data does not hold one. */
export function coordinate(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** The extent of the points, or null when there are none. */
export function boundsOf(points: Iterable<Point>): Bounds | null {
  let bounds: Bounds | null = null;
  for (const point of points) {
    if (bounds === null) {
      bounds = { minX: point.x, maxX: point.x, minY: point.y, maxY: point.y };
    } else {
      bounds.minX = Math.min(bounds.minX, point.x);
      bounds.maxX = Math.max(bounds.maxX, point.x);
      bounds.minY = Math.min(bounds.minY, point.y);
      bounds.maxY = Math.max(bounds.maxY, point.y);
    }
  }
  return bounds;
}

/**
 * The projection that shows all of `bounds` inside the viewport's padding, as
 * large as it will go without stretching either axis, and centred.
 */
export function fitBounds(bounds: Bounds, viewport: Viewport): Projection {
  const width = bounds.maxX - bounds.minX;
  const height = bounds.maxY - bounds.minY;
  const availableWidth = Math.max(viewport.width - 2 * viewport.padding, 1);
  const availableHeight = Math.max(viewport.height - 2 * viewport.padding, 1);
  // An extent with no width, or none at all, has no scale of its own to keep;
  // it is limited by the other axis, or drawn at one unit per unit.
  const scales = [
    width > 0 ? availableWidth / width : null,
    height > 0 ? availableHeight / height : null
  ].filter((scale): scale is number => scale !== null);
  return {
    scale: scales.length ? Math.min(...scales) : 1,
    center: { x: (bounds.minX + bounds.maxX) / 2, y: (bounds.minY + bounds.maxY) / 2 },
    viewport
  };
}

/** A data point in viewport units. Y is flipped: up in the data is up on screen. */
export function project(projection: Projection, point: Point): Point {
  return {
    x: projection.viewport.width / 2 + (point.x - projection.center.x) * projection.scale,
    y: projection.viewport.height / 2 - (point.y - projection.center.y) * projection.scale
  };
}

export type ReplayCar = Point & { driver: string; speedKph: number | null };

/** The cars of one frame that have a driver and a position. */
export function replayCars(frame: PositionReplayFrame): ReplayCar[] {
  const cars: ReplayCar[] = [];
  for (const position of frame.positions) {
    const x = coordinate(position.x);
    const y = coordinate(position.y);
    const driver = position.driver_code;
    if (x !== null && y !== null && typeof driver === "string" && driver !== "") {
      cars.push({ driver, x, y, speedKph: coordinate(position.speed_kph) });
    }
  }
  return cars;
}

/**
 * The extent of every car position in every frame. This is the replay's
 * domain: it does not depend on which frame is on screen.
 */
export function replayBounds(frames: ReadonlyArray<PositionReplayFrame>): Bounds | null {
  return boundsOf(frames.flatMap(replayCars));
}

/** The size of the cell within which outline dots are merged, in viewport units. */
const OUTLINE_CELL = 3;

/**
 * An SVG path of one dot per place a car has been, which together trace the
 * circuit. Only the first position in each cell is drawn, so the path stays
 * small however many frames there are. Stroke it with round caps.
 */
export function outlinePath(frames: ReadonlyArray<PositionReplayFrame>, projection: Projection): string {
  const taken = new Set<string>();
  const dots: string[] = [];
  for (const frame of frames) {
    for (const car of replayCars(frame)) {
      const at = project(projection, car);
      const cell = `${Math.round(at.x / OUTLINE_CELL)},${Math.round(at.y / OUTLINE_CELL)}`;
      if (!taken.has(cell)) {
        taken.add(cell);
        dots.push(`M${at.x.toFixed(1)} ${at.y.toFixed(1)}h0`);
      }
    }
  }
  return dots.join("");
}
