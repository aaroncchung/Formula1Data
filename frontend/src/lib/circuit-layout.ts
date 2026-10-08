/**
 * How a session's track maps are laid out: turned the way F1 draws the
 * circuit, with the circuit's official corners marked on them.
 *
 * Both come from the session's `corners.json`, which is the circuit's own
 * map: where each corner is, in the units of the position data, and by how
 * much to turn everything so that the circuit sits as it does on F1's
 * graphics. The publisher checks that map against a lap of the session and
 * says whether the corners lie on the line that was driven (`fits_track`).
 * Only then is any of it used here. A map of another layout of the circuit
 * would put the numbers in the infield and turn the track to an angle that
 * means nothing, so when it does not fit the maps are drawn as the position
 * data has them, with no corners, and say so.
 */

import type { Corners } from "./published/types.ts";
import { boundsOf, fitBounds, project } from "./track-map.ts";
import type { Point, Projection, Viewport } from "./track-map.ts";

/** A point turned about the origin, anticlockwise, by an angle in degrees. */
export function turned(point: Point, degrees: number): Point {
  if (degrees === 0) {
    return point;
  }
  const angle = (degrees * Math.PI) / 180;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return { x: point.x * cos - point.y * sin, y: point.x * sin + point.y * cos };
}

export type CornerMark = {
  /** The circuit's own name for the corner: "1", or "14A" where several corners share a number. */
  readonly label: string;
  /** Where the corner is, in the position data's units, turned as the map is. */
  readonly at: Point;
  /**
   * Which way its label lies from it, as a step of length one in the same
   * turned axes: the side of the track the circuit's map keeps clear for it.
   * Null when the map gives no direction.
   */
  readonly towardsLabel: Point | null;
  /** Metres from the start line; null when the corner could not be placed along the lap. */
  readonly distance_m: number | null;
};

export type CircuitLayout = {
  /**
   * `drawn`: the corners fit this session's track and are marked. `off_track`:
   * the session has a corner map and it is not of the track that was driven.
   * `unchecked`: it has one and no lap to check it against. `absent`: it has
   * none.
   */
  readonly status: "drawn" | "off_track" | "unchecked" | "absent";
  /** Degrees every position is turned by before it is drawn. 0 unless the corners are drawn. */
  readonly rotation: number;
  readonly corners: ReadonlyArray<CornerMark>;
};

/** The layout of a session's maps from its corner map, or the plain layout when it has none it can use. */
export function circuitLayout(corners: Corners | null): CircuitLayout {
  if (!corners || corners.corners.length === 0) {
    return { status: "absent", rotation: 0, corners: [] };
  }
  if (corners.fits_track === null) {
    return { status: "unchecked", rotation: 0, corners: [] };
  }
  if (!corners.fits_track) {
    return { status: "off_track", rotation: 0, corners: [] };
  }
  const rotation = corners.rotation ?? 0;
  return {
    status: "drawn",
    rotation,
    corners: corners.corners.map((corner) => ({
      label: `${corner.number}${corner.letter ?? ""}`,
      at: turned({ x: corner.x, y: corner.y }, rotation),
      // The map gives the label's direction in its own axes, before the turn.
      towardsLabel: corner.angle === null ? null : turned({ x: 1, y: 0 }, corner.angle + rotation),
      distance_m: corner.distance_m
    }))
  };
}

/** What a map says about its corners when it shows none although the session has a corner map; null otherwise. */
export function layoutNote(layout: CircuitLayout): string | null {
  switch (layout.status) {
    case "off_track":
      return "The circuit's corners are not marked: the corner map archived for this session does not lie on the line the cars drove.";
    case "unchecked":
      return "The circuit's corners are not marked: no lap of this session has the position data to check them against.";
    case "drawn":
    case "absent":
      return null;
  }
}

/** A corner where a map draws it, in the map's own units. */
export type PlacedCorner = { readonly label: string; readonly at: Point; readonly labelAt: Point };

export type TrackMap = {
  readonly projection: Projection;
  /** A position of the data as a point of the map, turned the way the circuit is drawn. */
  place(position: Point): Point;
  readonly corners: ReadonlyArray<PlacedCorner>;
};

/**
 * One map of a session: every position that will be drawn, fitted to the
 * viewport at one scale after being turned, and the corners placed on it.
 * `labelDistance` is how far from its corner a label is drawn, in the map's
 * units, so that labels sit the same distance off the track at any size; the
 * viewport's padding has to leave room for it. Null when there is nothing to
 * draw.
 */
export function trackMap(
  positions: Iterable<Point>,
  layout: CircuitLayout,
  viewport: Viewport,
  labelDistance: number
): TrackMap | null {
  const turnedPositions = Array.from(positions, (position) => turned(position, layout.rotation));
  // The corners are on the track, so they add nothing to its extent unless
  // the positions drawn cover only part of the lap.
  const bounds = boundsOf([...turnedPositions, ...layout.corners.map((corner) => corner.at)]);
  if (turnedPositions.length === 0 || !bounds) {
    return null;
  }
  const projection = fitBounds(bounds, viewport);
  return {
    projection,
    place: (position) => project(projection, turned(position, layout.rotation)),
    corners: layout.corners.map((corner) => {
      const at = project(projection, corner.at);
      const towards = corner.towardsLabel;
      return {
        label: corner.label,
        at,
        // Up in the data is up on the map, so the step's Y is subtracted.
        labelAt: towards ? { x: at.x + towards.x * labelDistance, y: at.y - towards.y * labelDistance } : at
      };
    })
  };
}

// The position data is in tenths of a metre.
const POSITION_UNITS_PER_METRE = 10;
// A lap passes a corner where its line comes this near the corner's place.
// The corners of the 2026 circuits lie within 20 m of the line a fast lap takes.
const CORNER_REACH_M = 50;
// And, where the corner map says how far round the lap the corner is, only
// this far from there, so that a stretch of track that passes close by (the
// two sides of a hairpin, a crossover) is never taken for the corner. Laps
// disagree about distance by about 1%, which on the longest circuit is 70 m.
const CORNER_SEARCH_M = 200;
// Two neighbouring points of a line further apart than this have a hole
// between them, and nothing is placed on the line across it.
const LINE_STEP_M = 150;

/** A place on the line a lap drove, with how far round that lap it is. */
export type LinePoint = Point & { readonly distance_m: number };

/**
 * The corners a lap passes, each with how far round that lap it is, in the
 * order they come, for marking on the lap's own distance axis.
 *
 * A lap's distance is its own car's speed added up, and laps disagree by
 * tens of metres. The corner map's distances are along the lap the publisher
 * placed the corners on: turn 6 of the 2026 Austrian GP is 2,518 m round
 * that lap and 2,554 m round Stroll's lap 30. Marked at the first on the
 * second lap's axis, the line stands 36 m before the corner. So a corner is
 * marked where the lap drawn passes it, between the two samples either side,
 * and is left out where the lap has no position data near it.
 */
export function cornersOnLap(
  layout: CircuitLayout,
  line: ReadonlyArray<LinePoint>
): Array<{ label: string; distance_m: number }> {
  const reach = (CORNER_REACH_M * POSITION_UNITS_PER_METRE) ** 2;
  const turnedLine = line.map((point) => ({ ...turned(point, layout.rotation), distance_m: point.distance_m }));
  const marks: Array<{ label: string; distance_m: number }> = [];
  for (const corner of layout.corners) {
    let nearest: { off: number; distance_m: number } | null = null;
    const consider = (off: number, along: number) => {
      const expected = corner.distance_m;
      if (off > reach || (expected !== null && Math.abs(along - expected) > CORNER_SEARCH_M)) {
        return;
      }
      if (nearest === null || off < nearest.off) {
        nearest = { off, distance_m: along };
      }
    };
    turnedLine.forEach((point, index) => {
      consider((point.x - corner.at.x) ** 2 + (point.y - corner.at.y) ** 2, point.distance_m);
      const next = turnedLine[index + 1];
      if (!next || next.distance_m - point.distance_m > LINE_STEP_M) {
        return;
      }
      // The place on the line between this sample and the next that is nearest the corner.
      const stepX = next.x - point.x;
      const stepY = next.y - point.y;
      const length = stepX ** 2 + stepY ** 2;
      if (length === 0) {
        return;
      }
      const share = Math.min(1, Math.max(0, ((corner.at.x - point.x) * stepX + (corner.at.y - point.y) * stepY) / length));
      const off = (point.x + share * stepX - corner.at.x) ** 2 + (point.y + share * stepY - corner.at.y) ** 2;
      consider(off, point.distance_m + share * (next.distance_m - point.distance_m));
    });
    const found = nearest as { off: number; distance_m: number } | null;
    if (found !== null) {
      marks.push({ label: corner.label, distance_m: found.distance_m });
    }
  }
  return marks.sort((left, right) => left.distance_m - right.distance_m);
}
