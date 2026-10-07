import type { PositionReplay } from "./published/types.ts";

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

/** How many frames a replay has. A session with no position data has none. */
export function replayFrameCount(replay: PositionReplay): number {
  return replay.time_ms.length;
}

/**
 * The cars that have a position in one frame. A replay holds each car's
 * track as arrays with one entry for each frame, null in a frame the car has
 * no position for: such a car is left out of the frame, never drawn at the
 * origin as if it had been measured there. A car can have a position and no
 * speed, when its position data arrived and its car data did not.
 */
export function replayCars(replay: PositionReplay, frame: number): ReplayCar[] {
  const cars: ReplayCar[] = [];
  for (const car of replay.drivers) {
    const x = car.x[frame] ?? null;
    const y = car.y[frame] ?? null;
    if (x !== null && y !== null) {
      cars.push({ driver: car.driver_code, x, y, speedKph: car.speed_kph[frame] ?? null });
    }
  }
  return cars;
}

/**
 * Every position of every car in every frame, which between them trace the
 * circuit. Their extent is the replay's domain: it does not depend on which
 * frame is on screen.
 */
export function replayPositions(replay: PositionReplay): Point[] {
  const points: Point[] = [];
  for (const car of replay.drivers) {
    car.x.forEach((x, frame) => {
      const y = car.y[frame] ?? null;
      if (x !== null && y !== null) {
        points.push({ x, y });
      }
    });
  }
  return points;
}

/** The size of the cell within which outline dots are merged, in viewport units. */
const OUTLINE_CELL = 3;

/**
 * An SVG path of one dot per place a car has been, which together trace the
 * circuit. Only the first position in each cell is drawn, so the path stays
 * small however many positions there are. Stroke it with round caps.
 */
export function outlinePath(positions: Iterable<Point>, projection: Projection): string {
  const taken = new Set<string>();
  const dots: string[] = [];
  for (const position of positions) {
    const at = project(projection, position);
    const cell = `${Math.round(at.x / OUTLINE_CELL)},${Math.round(at.y / OUTLINE_CELL)}`;
    if (!taken.has(cell)) {
      taken.add(cell);
      dots.push(`M${at.x.toFixed(1)} ${at.y.toFixed(1)}h0`);
    }
  }
  return dots.join("");
}
