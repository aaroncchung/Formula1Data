import assert from "node:assert/strict";
import test from "node:test";

import {
  boundsOf,
  coordinate,
  fitBounds,
  outlinePath,
  project,
  replayBounds,
  replayCars
} from "../src/lib/track-map.ts";

const VIEWPORT = { width: 1000, height: 600, padding: 40 };

function frame(index, positions) {
  return {
    session_id: "2026-08-r",
    frame_index: index,
    lap_number: 1,
    timestamp_ms: index * 5000,
    positions: positions.map(([driver_code, x, y]) => ({ driver_code, x, y, speed_kph: 200, distance_m: 0 }))
  };
}

// The shape of the real replay: the grid is bunched on the start straight in
// the first frame, and the field only covers the circuit later on. Extents
// are those of sessions/2026-08-r/position-replay.json.
const FRAMES = [
  frame(0, [
    ["ALB", 1327, -1147],
    ["ALO", 1558, -1085],
    ["VER", 53, -1491]
  ]),
  frame(1, [
    ["ALB", -8237, 2355],
    ["ALO", 4247, 5680],
    ["VER", -4767, -2244]
  ]),
  frame(2, [["ALB", -415, -1617]])
];

function assertClose(actual, expected, message) {
  assert.ok(Math.abs(actual - expected) < 1e-6, `${message ?? "value"}: ${actual} is not ${expected}`);
}

test("the replay's extent covers every frame, not the one on screen", () => {
  assert.deepEqual(replayBounds(FRAMES), { minX: -8237, maxX: 4247, minY: -2244, maxY: 5680 });
});

test("the extent does not depend on the order of the frames", () => {
  assert.deepEqual(replayBounds([...FRAMES].reverse()), replayBounds(FRAMES));
});

test("one data unit is the same length on screen along both axes", () => {
  const projection = fitBounds(replayBounds(FRAMES), VIEWPORT);
  const origin = project(projection, { x: 0, y: 0 });
  const east = project(projection, { x: 1000, y: 0 });
  const north = project(projection, { x: 0, y: 1000 });

  assertClose(east.x - origin.x, origin.y - north.y, "1000 units east against 1000 units north");
  assertClose(east.y, origin.y, "moving east does not move north");
  assertClose(north.x, origin.x, "moving north does not move east");
});

test("every car of every frame lands inside the padded viewport", () => {
  const projection = fitBounds(replayBounds(FRAMES), VIEWPORT);

  for (const car of FRAMES.flatMap(replayCars)) {
    const at = project(projection, car);
    assert.ok(at.x >= VIEWPORT.padding - 1e-6 && at.x <= VIEWPORT.width - VIEWPORT.padding + 1e-6, `${car.driver} x ${at.x}`);
    assert.ok(at.y >= VIEWPORT.padding - 1e-6 && at.y <= VIEWPORT.height - VIEWPORT.padding + 1e-6, `${car.driver} y ${at.y}`);
  }
});

// The defect this replaces: the axes fitted themselves to the frame on screen,
// so the bunched grid of the first frame was blown up to fill the plot and the
// circuit rescaled as the cars spread out.
test("a bunched frame is drawn small, at the scale of the whole circuit", () => {
  const projection = fitBounds(replayBounds(FRAMES), VIEWPORT);
  const grid = boundsOf(replayCars(FRAMES[0]).map((car) => project(projection, car)));

  assert.ok(grid.maxX - grid.minX < 0.15 * VIEWPORT.width, `grid is ${grid.maxX - grid.minX} wide`);
  assert.ok(grid.maxY - grid.minY < 0.15 * VIEWPORT.height, `grid is ${grid.maxY - grid.minY} tall`);
});

test("a point on the circuit lands in the same place whichever frame is on screen", () => {
  const projection = fitBounds(replayBounds(FRAMES), VIEWPORT);
  const startLine = { x: 1327, y: -1147 };
  const placed = FRAMES.map(() => project(projection, startLine));

  assert.deepEqual(placed[1], placed[0]);
  assert.deepEqual(placed[2], placed[0]);
});

test("the circuit is centred in the viewport", () => {
  const bounds = replayBounds(FRAMES);
  const projection = fitBounds(bounds, VIEWPORT);
  const middle = project(projection, { x: (bounds.minX + bounds.maxX) / 2, y: (bounds.minY + bounds.maxY) / 2 });

  assertClose(middle.x, 500, "centre x");
  assertClose(middle.y, 300, "centre y");
});

test("north in the data is up on screen", () => {
  const projection = fitBounds(replayBounds(FRAMES), VIEWPORT);

  assert.ok(project(projection, { x: 0, y: 5000 }).y < project(projection, { x: 0, y: -2000 }).y);
});

test("a wide circuit is limited by the width and a tall one by the height", () => {
  const wide = fitBounds({ minX: 0, maxX: 10000, minY: 0, maxY: 1000 }, VIEWPORT);
  const tall = fitBounds({ minX: 0, maxX: 1000, minY: 0, maxY: 10000 }, VIEWPORT);

  assertClose(wide.scale, 920 / 10000, "wide scale");
  assertClose(tall.scale, 520 / 10000, "tall scale");
  assertClose(project(wide, { x: 0, y: 0 }).x, 40, "wide circuit touches the left padding");
  assertClose(project(tall, { x: 0, y: 0 }).y, 560, "tall circuit touches the bottom padding");
});

test("a single position still gets a finite projection, at the centre", () => {
  const projection = fitBounds(boundsOf([{ x: -415, y: -1617 }]), VIEWPORT);

  assert.ok(Number.isFinite(projection.scale));
  assert.deepEqual(project(projection, { x: -415, y: -1617 }), { x: 500, y: 300 });
});

test("positions along one straight line are fitted along that line", () => {
  const projection = fitBounds({ minX: 0, maxX: 2000, minY: 7, maxY: 7 }, VIEWPORT);

  assertClose(projection.scale, 920 / 2000, "scale");
  assertClose(project(projection, { x: 2000, y: 7 }).y, 300, "the line runs through the middle");
});

test("no frames, or frames without a position, have no extent", () => {
  assert.equal(replayBounds([]), null);
  assert.equal(replayBounds([frame(0, [["ALB", null, null]])]), null);
  assert.equal(boundsOf([]), null);
});

// The old chart ran `Number()` over the coordinates, which puts a car with no
// position at the origin as if it had been measured there.
test("a car without a position is left out, not drawn at the origin", () => {
  const cars = replayCars(
    frame(0, [
      ["ALB", 100, 200],
      ["ALO", null, 200],
      ["ANT", 100, null],
      ["BEA", Number.NaN, 200],
      ["BOR", "", ""],
      ["BOT", "not a number", 1]
    ])
  );

  assert.deepEqual(cars, [{ driver: "ALB", x: 100, y: 200, speedKph: 200 }]);
});

test("a position without a driver is left out", () => {
  assert.deepEqual(replayCars(frame(0, [[null, 100, 200], ["", 100, 200]])), []);
});

test("coordinates may arrive as numbers or numeric strings", () => {
  assert.equal(coordinate(12.5), 12.5);
  assert.equal(coordinate("-8237.59"), -8237.59);
  assert.equal(coordinate(0), 0);
  assert.equal(coordinate("0"), 0);
  assert.equal(coordinate(null), null);
  assert.equal(coordinate(undefined), null);
  assert.equal(coordinate(""), null);
  assert.equal(coordinate("  "), null);
  assert.equal(coordinate(Number.POSITIVE_INFINITY), null);
  assert.equal(coordinate(true), null);
});

test("a car's speed is optional", () => {
  const withoutSpeed = { ...frame(0, [["ALB", 1, 2]]) };
  withoutSpeed.positions = [{ driver_code: "ALB", x: 1, y: 2 }];

  assert.deepEqual(replayCars(withoutSpeed), [{ driver: "ALB", x: 1, y: 2, speedKph: null }]);
});

test("the circuit outline has one dot per place a car has been", () => {
  const frames = [
    frame(0, [["ALB", 0, 0]]),
    frame(1, [["ALB", 0, 0]]),
    frame(2, [["ALB", 5000, 0]]),
    frame(3, [["ALO", 5000, 0.001]])
  ];
  const outline = outlinePath(frames, fitBounds(replayBounds(frames), VIEWPORT));

  assert.equal(outline.match(/M/g)?.length, 2);
  assert.match(outline, /^(M-?\d+\.\d -?\d+\.\dh0)+$/);
});

test("the outline grows with the circuit covered, not with the number of frames", () => {
  const lap = Array.from({ length: 50 }, (_, index) => frame(index, [["ALB", index * 100, 0]]));
  const projection = fitBounds(replayBounds(lap), VIEWPORT);
  const once = outlinePath(lap, projection);
  const twentyLaps = outlinePath(Array.from({ length: 20 }, () => lap).flat(), projection);

  assert.equal(twentyLaps, once);
});

test("the outline of an empty replay is an empty path", () => {
  assert.equal(outlinePath([], fitBounds({ minX: 0, maxX: 1, minY: 0, maxY: 1 }, VIEWPORT)), "");
});
