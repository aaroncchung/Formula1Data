import assert from "node:assert/strict";
import test from "node:test";

import {
  boundsOf,
  fitBounds,
  outlinePath,
  project,
  replayCars,
  replayFrameCount,
  replayPositions
} from "../src/lib/track-map.ts";

const VIEWPORT = { width: 1000, height: 600, padding: 40 };

/** The extent a replay is fitted to: that of every position in every frame. */
const replayBounds = (replay) => boundsOf(replayPositions(replay));

/**
 * A replay in the published shape, from one list for each car of where it
 * was in each frame: `[x, y]`, or null for a frame the car has no position
 * in. A frame is five seconds, and the session is on lap 1 throughout.
 */
function replay(tracks) {
  const frames = Math.max(0, ...Object.values(tracks).map((track) => track.length));
  const column = (track, pick) => Array.from({ length: frames }, (_, frame) => pick(track[frame] ?? null));
  return {
    interval_ms: 5000,
    time_ms: Array.from({ length: frames }, (_, frame) => 3_300_000 + frame * 5000),
    lap_number: Array.from({ length: frames }, () => 1),
    drivers: Object.entries(tracks).map(([driver_code, track]) => ({
      driver_code,
      x: column(track, (at) => (at ? at[0] : null)),
      y: column(track, (at) => (at ? at[1] : null)),
      speed_kph: column(track, (at) => (at ? 200 : null)),
      distance_m: column(track, (at) => (at ? 0 : null))
    }))
  };
}

// The shape of a real replay: the grid is bunched on the start straight in
// the first frame, and the field only covers the circuit later on. Albon
// alone is still running in the third frame. Extents are those of the 2026
// Austrian GP.
const REPLAY = replay({
  ALB: [[1327, -1147], [-8237, 2355], [-415, -1617]],
  ALO: [[1558, -1085], [4247, 5680], null],
  VER: [[53, -1491], [-4767, -2244], null]
});
const FRAMES = [0, 1, 2];

function assertClose(actual, expected, message) {
  assert.ok(Math.abs(actual - expected) < 1e-6, `${message ?? "value"}: ${actual} is not ${expected}`);
}

test("a replay has one frame for each entry of its clock", () => {
  assert.equal(replayFrameCount(REPLAY), 3);
  assert.equal(replayFrameCount(replay({})), 0);
});

test("the replay's extent covers every frame, not the one on screen", () => {
  assert.deepEqual(replayBounds(REPLAY), { minX: -8237, maxX: 4247, minY: -2244, maxY: 5680 });
});

test("one data unit is the same length on screen along both axes", () => {
  const projection = fitBounds(replayBounds(REPLAY), VIEWPORT);
  const origin = project(projection, { x: 0, y: 0 });
  const east = project(projection, { x: 1000, y: 0 });
  const north = project(projection, { x: 0, y: 1000 });

  assertClose(east.x - origin.x, origin.y - north.y, "1000 units east against 1000 units north");
  assertClose(east.y, origin.y, "moving east does not move north");
  assertClose(north.x, origin.x, "moving north does not move east");
});

test("every car of every frame lands inside the padded viewport", () => {
  const projection = fitBounds(replayBounds(REPLAY), VIEWPORT);

  for (const car of FRAMES.flatMap((frame) => replayCars(REPLAY, frame))) {
    const at = project(projection, car);
    assert.ok(at.x >= VIEWPORT.padding - 1e-6 && at.x <= VIEWPORT.width - VIEWPORT.padding + 1e-6, `${car.driver} x ${at.x}`);
    assert.ok(at.y >= VIEWPORT.padding - 1e-6 && at.y <= VIEWPORT.height - VIEWPORT.padding + 1e-6, `${car.driver} y ${at.y}`);
  }
});

// The defect this once replaced: the axes fitted themselves to the frame on
// screen, so the bunched grid of the first frame was blown up to fill the
// plot and the circuit rescaled as the cars spread out.
test("a bunched frame is drawn small, at the scale of the whole circuit", () => {
  const projection = fitBounds(replayBounds(REPLAY), VIEWPORT);
  const grid = boundsOf(replayCars(REPLAY, 0).map((car) => project(projection, car)));

  assert.ok(grid.maxX - grid.minX < 0.15 * VIEWPORT.width, `grid is ${grid.maxX - grid.minX} wide`);
  assert.ok(grid.maxY - grid.minY < 0.15 * VIEWPORT.height, `grid is ${grid.maxY - grid.minY} tall`);
});

test("the circuit is centred in the viewport", () => {
  const bounds = replayBounds(REPLAY);
  const projection = fitBounds(bounds, VIEWPORT);
  const middle = project(projection, { x: (bounds.minX + bounds.maxX) / 2, y: (bounds.minY + bounds.maxY) / 2 });

  assertClose(middle.x, 500, "centre x");
  assertClose(middle.y, 300, "centre y");
});

test("north in the data is up on screen", () => {
  const projection = fitBounds(replayBounds(REPLAY), VIEWPORT);

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

test("a replay with no frames, or with no position in any, has no extent", () => {
  assert.equal(replayBounds(replay({})), null);
  assert.equal(replayBounds(replay({ ALB: [null, null] })), null);
  assert.equal(boundsOf([]), null);
});

// A car with no position in a frame has null there. It is not a car at the
// origin: drawn there it would sit in the infield as if it had been measured.
test("a car without a position in a frame is left out of it, not drawn at the origin", () => {
  assert.deepEqual(replayCars(REPLAY, 2), [{ driver: "ALB", x: -415, y: -1617, speedKph: 200 }]);
  assert.deepEqual(replayCars(REPLAY, 1).map((car) => car.driver), ["ALB", "ALO", "VER"]);
  // Half a position is none.
  const half = replay({ ALB: [[100, 200]] });
  half.drivers[0].y[0] = null;
  assert.deepEqual(replayCars(half, 0), []);
  assert.deepEqual(replayPositions(half), []);
});

test("a frame the replay does not have has no cars", () => {
  assert.deepEqual(replayCars(REPLAY, 3), []);
  assert.deepEqual(replayCars(REPLAY, -1), []);
});

// A car's position can arrive without its car data, and then it has a place
// on the map and no speed.
test("a car with a position and no speed is still drawn, without a speed", () => {
  const silent = replay({ ALB: [[1, 2]] });
  silent.drivers[0].speed_kph[0] = null;
  silent.drivers[0].distance_m[0] = null;

  assert.deepEqual(replayCars(silent, 0), [{ driver: "ALB", x: 1, y: 2, speedKph: null }]);
});

test("the circuit outline has one dot per place a car has been", () => {
  const lap = replay({ ALB: [[0, 0], [0, 0], [5000, 0], null], ALO: [null, null, null, [5000, 0.001]] });
  const outline = outlinePath(replayPositions(lap), fitBounds(replayBounds(lap), VIEWPORT));

  assert.equal(outline.match(/M/g)?.length, 2);
  assert.match(outline, /^(M-?\d+\.\d -?\d+\.\dh0)+$/);
});

test("the outline grows with the circuit covered, not with the number of frames", () => {
  const once = Array.from({ length: 50 }, (_, index) => [index * 100, 0]);
  const lap = replay({ ALB: once });
  const twentyLaps = replay({ ALB: Array.from({ length: 20 }, () => once).flat() });
  const projection = fitBounds(replayBounds(lap), VIEWPORT);

  assert.equal(outlinePath(replayPositions(twentyLaps), projection), outlinePath(replayPositions(lap), projection));
});

test("the outline of an empty replay is an empty path", () => {
  assert.equal(outlinePath([], fitBounds({ minX: 0, maxX: 1, minY: 0, maxY: 1 }, VIEWPORT)), "");
});
