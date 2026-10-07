import assert from "node:assert/strict";
import test from "node:test";

import { circuitLayout, cornersAlongLap, layoutNote, trackMap, turned } from "../src/lib/circuit-layout.ts";

const VIEWPORT = { width: 600, height: 400, padding: 40 };

/** A corner as corners.json has one. */
const corner = (number, x, y, fields = {}) => ({ number, letter: null, x, y, angle: 0, distance_m: number * 100, ...fields });

/** corners.json: the circuit's corner map, and the publisher's check of it against a lap of the session. */
function cornerMap(corners, fields = {}) {
  return {
    corners,
    distance_source: "archive",
    fits_track: true,
    off_track_m: 5.9,
    reference_lap: { driver_code: "ANT", lap_number: 59, length_m: 4290.5 },
    rotation: 0,
    ...fields
  };
}

function assertPoint(actual, expected, message) {
  assert.ok(
    Math.abs(actual.x - expected.x) < 1e-6 && Math.abs(actual.y - expected.y) < 1e-6,
    `${message ?? "point"}: (${actual.x}, ${actual.y}) is not (${expected.x}, ${expected.y})`
  );
}

// ---------------------------------------------------------------------------
// Turning
// ---------------------------------------------------------------------------

test("a point is turned anticlockwise about the origin", () => {
  assertPoint(turned({ x: 100, y: 0 }, 90), { x: 0, y: 100 });
  assertPoint(turned({ x: 100, y: 0 }, 180), { x: -100, y: 0 });
  assertPoint(turned({ x: 0, y: 100 }, 90), { x: -100, y: 0 });
  assertPoint(turned({ x: 100, y: 0 }, -90), { x: 0, y: -100 });
  assertPoint(turned({ x: 3, y: 4 }, 360), { x: 3, y: 4 });
});

test("no turn leaves a point exactly where it was", () => {
  const point = { x: -3064, y: -2208.5 };

  assert.equal(turned(point, 0), point);
});

// ---------------------------------------------------------------------------
// Which corner maps are used
// ---------------------------------------------------------------------------

test("a corner map that fits the session's track is drawn, by the circuit's own numbers and letters", () => {
  const layout = circuitLayout(
    cornerMap([corner(1, 100, 0), corner(14, 200, 0, { letter: "A" }), corner(14, 300, 0, { letter: "B" })])
  );

  assert.equal(layout.status, "drawn");
  assert.deepEqual(layout.corners.map((item) => item.label), ["1", "14A", "14B"]);
  assert.equal(layoutNote(layout), null);
});

// The publisher checks the archived map against a lap of the session. A map
// of another layout of the circuit would put the numbers in the infield.
test("a corner map that does not lie on the line that was driven is not drawn, and the page says so", () => {
  const layout = circuitLayout(cornerMap([corner(1, 100, 0)], { fits_track: false, off_track_m: 412.7, rotation: 44 }));

  assert.equal(layout.status, "off_track");
  assert.deepEqual(layout.corners, []);
  // Its rotation is of the same map, and is not trusted either.
  assert.equal(layout.rotation, 0);
  assert.match(layoutNote(layout), /does not lie on the line the cars drove/);
});

test("a corner map there was no lap to check against is not drawn either", () => {
  const layout = circuitLayout(cornerMap([corner(1, 100, 0)], { fits_track: null, off_track_m: null, reference_lap: null }));

  assert.equal(layout.status, "unchecked");
  assert.deepEqual(layout.corners, []);
  assert.match(layoutNote(layout), /no lap of this session has the position data/);
});

test("a session with no corner map, or an empty one, has a plain layout and nothing to explain", () => {
  for (const corners of [null, cornerMap([], { fits_track: null, rotation: null, distance_source: null })]) {
    const layout = circuitLayout(corners);

    assert.deepEqual(layout, { status: "absent", rotation: 0, corners: [] });
    assert.equal(layoutNote(layout), null);
  }
});

// ---------------------------------------------------------------------------
// Placing corners
// ---------------------------------------------------------------------------

test("a corner is turned with the map, and its label lies the way the corner map points", () => {
  // The map says: turn everything a quarter turn, and this corner's label is
  // straight along X from it, before the turn.
  const layout = circuitLayout(cornerMap([corner(1, 1000, 0, { angle: 0 })], { rotation: 90 }));
  const [mark] = layout.corners;

  assert.equal(layout.rotation, 90);
  assertPoint(mark.at, { x: 0, y: 1000 }, "corner");
  assertPoint(mark.towardsLabel, { x: 0, y: 1 }, "label direction");
});

test("the direction of a label is the corner's own angle when the map is not turned", () => {
  const [east, north, southWest] = circuitLayout(
    cornerMap([corner(1, 0, 0, { angle: 0 }), corner(2, 0, 0, { angle: 90 }), corner(3, 0, 0, { angle: -135 })])
  ).corners;

  assertPoint(east.towardsLabel, { x: 1, y: 0 });
  assertPoint(north.towardsLabel, { x: 0, y: 1 });
  assertPoint(southWest.towardsLabel, { x: -Math.SQRT1_2, y: -Math.SQRT1_2 });
});

test("a rotation the map does not give is no turn, and an angle it does not give is no direction", () => {
  const layout = circuitLayout(cornerMap([corner(1, 100, 50, { angle: null })], { rotation: null }));

  assert.equal(layout.rotation, 0);
  assert.deepEqual(layout.corners[0].at, { x: 100, y: 50 });
  assert.equal(layout.corners[0].towardsLabel, null);
});

// ---------------------------------------------------------------------------
// A map of the track
// ---------------------------------------------------------------------------

// A square circuit, 1,000 units a side, with a corner at each of two ends.
const SQUARE = [{ x: 0, y: 0 }, { x: 1000, y: 0 }, { x: 1000, y: 1000 }, { x: 0, y: 1000 }];

test("positions and corners land on one map, turned together", () => {
  const layout = circuitLayout(cornerMap([corner(1, 1000, 0, { angle: 0 })], { rotation: 90 }));
  const map = trackMap(SQUARE, layout, VIEWPORT, 20);

  // The corner sits exactly where the track position it marks is drawn.
  assertPoint(map.corners[0].at, map.place({ x: 1000, y: 0 }), "corner on the track");
  // Turned a quarter turn: what was the east end of the bottom edge is now up.
  assert.ok(map.place({ x: 1000, y: 0 }).y < map.place({ x: 0, y: 0 }).y);
});

test("a label is a fixed distance from its corner on the map, whatever the size of the circuit", () => {
  const layout = circuitLayout(cornerMap([corner(1, 1000, 0, { angle: 0 }), corner(2, 1000, 1000, { angle: 90 })]));
  const large = SQUARE.map((point) => ({ x: point.x * 10, y: point.y * 10 }));

  for (const positions of [SQUARE, large]) {
    const [east, north] = trackMap(positions, layout, VIEWPORT, 20).corners;

    assertPoint(east.labelAt, { x: east.at.x + 20, y: east.at.y }, "label to the east");
    // Up in the data is up on the map.
    assertPoint(north.labelAt, { x: north.at.x, y: north.at.y - 20 }, "label to the north");
  }
});

test("every position and every corner is inside the padded viewport", () => {
  const layout = circuitLayout(cornerMap([corner(1, 1000, 0), corner(2, 0, 1000)], { rotation: 33 }));
  const map = trackMap(SQUARE, layout, VIEWPORT, 20);

  for (const at of [...SQUARE.map((point) => map.place(point)), ...map.corners.map((item) => item.at)]) {
    assert.ok(at.x >= VIEWPORT.padding - 1e-6 && at.x <= VIEWPORT.width - VIEWPORT.padding + 1e-6, `x ${at.x}`);
    assert.ok(at.y >= VIEWPORT.padding - 1e-6 && at.y <= VIEWPORT.height - VIEWPORT.padding + 1e-6, `y ${at.y}`);
  }
});

test("a corner with no direction is labelled where it is", () => {
  const layout = circuitLayout(cornerMap([corner(1, 1000, 0, { angle: null })]));
  const [mark] = trackMap(SQUARE, layout, VIEWPORT, 20).corners;

  assert.deepEqual(mark.labelAt, mark.at);
});

test("a plain layout draws the positions as they are, with no corners", () => {
  const map = trackMap(SQUARE, circuitLayout(null), VIEWPORT, 20);

  assert.deepEqual(map.corners, []);
  assertPoint(map.place({ x: 500, y: 500 }), { x: 300, y: 200 }, "centre");
});

test("with no positions there is no map, corners or not", () => {
  assert.equal(trackMap([], circuitLayout(cornerMap([corner(1, 1000, 0)])), VIEWPORT, 20), null);
  assert.equal(trackMap([], circuitLayout(null), VIEWPORT, 20), null);
});

// ---------------------------------------------------------------------------
// Corners along the lap
// ---------------------------------------------------------------------------

test("corners are listed along the lap in the order they come, without the ones that could not be placed", () => {
  const layout = circuitLayout(
    cornerMap([
      corner(2, 0, 0, { distance_m: 906.9 }),
      corner(1, 0, 0, { distance_m: 256.7 }),
      corner(3, 0, 0, { distance_m: null })
    ])
  );

  assert.deepEqual(cornersAlongLap(layout), [
    { label: "1", distance_m: 256.7 },
    { label: "2", distance_m: 906.9 }
  ]);
  assert.deepEqual(cornersAlongLap(circuitLayout(null)), []);
});
