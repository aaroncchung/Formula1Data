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

/** The corners that have a place along the lap, in the order they come, for marking on a distance axis. */
export function cornersAlongLap(layout: CircuitLayout): Array<{ label: string; distance_m: number }> {
  return layout.corners
    .flatMap((corner) => (corner.distance_m === null ? [] : [{ label: corner.label, distance_m: corner.distance_m }]))
    .sort((left, right) => left.distance_m - right.distance_m);
}
