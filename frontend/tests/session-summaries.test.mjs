import assert from "node:assert/strict";
import test from "node:test";

import { PublishedDataError } from "../src/lib/published/errors.ts";
import {
  defaultTelemetryLaps,
  driverCards,
  readField,
  readRacePace,
  readSessionFigures,
  readStrategy,
  readTelemetryIndex,
  teamCards
} from "../src/lib/session-summaries.ts";
import { shareWhilePending } from "../src/lib/shared-request.ts";
import { telemetryComparerOf } from "../src/lib/view-telemetry.ts";

/** A pinned view over in-memory files. A path it does not list is refused, as the real one refuses it. */
function viewOf(files, sessionKey = 11315) {
  const reads = [];
  return {
    reads,
    pointer: { session_key: sessionKey },
    manifest: { files: Object.keys(files).map((path) => ({ path })) },
    has: (path) => path in files,
    read: async (path) => {
      reads.push(path);
      if (!(path in files)) {
        throw new PublishedDataError("not_in_manifest", `${path} is not in the manifest.`, { path });
      }
      const file = files[path];
      if (file instanceof Error) {
        throw file;
      }
      return file;
    }
  };
}

const team = (id, name, color) => ({ team_id: id, name, color });
const MERCEDES = team("mercedes", "Mercedes", "#00D7B6");
const RED_BULL = team("red-bull", "Red Bull", "#4781D7");

const DRIVERS = [
  { driver_id: "rus", code: "RUS", full_name: "George Russell", number: 63, team: MERCEDES },
  { driver_id: "ver", code: "VER", full_name: "Max Verstappen", number: 3, team: RED_BULL },
  { driver_id: "ant", code: "ANT", full_name: "Andrea Kimi Antonelli", number: 12, team: MERCEDES }
];
const RESULTS = [
  { session_id: "s", position: 1, driver_code: "RUS", points: 25 },
  { session_id: "s", position: 2, driver_code: "VER", points: 18 },
  { session_id: "s", position: 5, driver_code: "ANT", points: 10 }
];
const RACE_PACE = {
  session_id: "s",
  drivers: [
    { driver_code: "RUS", median_lap_ms: 68100, lap_count: 60 },
    { driver_code: "ANT", median_lap_ms: 68350, lap_count: 58 }
  ],
  stints: [],
  caveats: []
};
const IDEAL_LAPS = { session_id: "s", rows: [{ driver_code: "VER", ideal_lap_ms: 66900, delta_to_ideal_ms: 120 }] };

// ---------------------------------------------------------------------------
// Readers
// ---------------------------------------------------------------------------

test("the strategy page reads its three files and nothing else", async () => {
  const strategy = { session_id: "s", stints: [], compound_usage: {}, pit_stops: [], undercut_overcut: [], caveats: [] };
  const view = viewOf({
    "stints.json": [{ driver_code: "RUS", stint: 1 }],
    "pit-stops.json": [],
    "analysis/strategy.json": strategy,
    "laps.json": [],
    "position-replay.json": []
  });

  const read = await readStrategy(view);

  assert.deepEqual(read, { stints: [{ driver_code: "RUS", stint: 1 }], pitStops: [], strategy });
  assert.deepEqual([...view.reads].sort(), ["analysis/strategy.json", "pit-stops.json", "stints.json"]);
});

test("the field is the drivers, with whatever else the generation holds beside them", async () => {
  const full = viewOf({
    "drivers.json": DRIVERS,
    "results.json": RESULTS,
    "analysis/race-pace.json": RACE_PACE,
    "analysis/ideal-laps.json": IDEAL_LAPS
  });
  assert.deepEqual(await readField(full), {
    drivers: DRIVERS,
    results: RESULTS,
    racePace: RACE_PACE,
    idealLaps: IDEAL_LAPS
  });

  const bare = viewOf({ "drivers.json": DRIVERS });
  assert.deepEqual(await readField(bare), { drivers: DRIVERS, results: null, racePace: null, idealLaps: null });
  assert.deepEqual(bare.reads, ["drivers.json"]);
});

test("a generation without drivers fails the field instead of showing an empty one", async () => {
  await assert.rejects(
    () => readField(viewOf({ "results.json": RESULTS })),
    (error) => error.code === "not_in_manifest"
  );
});

test("a failed read is passed on, so the page can tell a missing generation from a missing file", async () => {
  const gone = new PublishedDataError("generation_gone", "The generation is gone.", {});

  await assert.rejects(
    () => readStrategy(viewOf({ "stints.json": gone, "pit-stops.json": [] })),
    (error) => error.code === "generation_gone"
  );
});

test("an artifact of the wrong kind is invalid before a page maps over it", async () => {
  const cases = [
    [() => readField(viewOf({ "drivers.json": { drivers: [] } })), /drivers\.json is not a list/],
    [() => readStrategy(viewOf({ "stints.json": "none" })), /stints\.json is not a list/],
    [() => readStrategy(viewOf({ "analysis/strategy.json": [] })), /analysis\/strategy\.json is not an object/],
    [() => readStrategy(viewOf({ "analysis/strategy.json": {} })), /has no list named caveats/],
    [() => readRacePace(viewOf({ "analysis/race-pace.json": { drivers: null } })), /has no list named drivers/],
    [() => readTelemetryIndex(viewOf({ "telemetry/index.json": { laps: {} } })), /has no list named laps/],
    [() => readSessionFigures(viewOf({ "summary.json": null })), /summary\.json is not an object/]
  ];

  for (const [read, message] of cases) {
    await assert.rejects(read, (error) => error.code === "invalid_artifact" && message.test(error.message), String(message));
  }
});

test("the headline figures and the telemetry index are absent when the generation has none", async () => {
  const view = viewOf({ "drivers.json": DRIVERS });

  assert.deepEqual(await readSessionFigures(view), { summary: null, idealLaps: null });
  assert.equal(await readRacePace(view), null);
  assert.equal(await readTelemetryIndex(view), null);
  assert.deepEqual(view.reads, []);
});

// ---------------------------------------------------------------------------
// Driver and team cards
// ---------------------------------------------------------------------------

test("a driver card carries the driver's own finish, pace and ideal lap", () => {
  const cards = driverCards({ drivers: DRIVERS, results: RESULTS, racePace: RACE_PACE, idealLaps: IDEAL_LAPS });

  assert.deepEqual(
    cards.map((card) => [card.driver.code, card.finish, card.medianLapMs, card.idealLapMs]),
    [
      ["RUS", 1, 68100, null],
      ["VER", 2, null, 66900],
      ["ANT", 5, 68350, null]
    ]
  );
});

test("a driver card is blank, not zero, where the session has no figure", () => {
  const [card] = driverCards({ drivers: DRIVERS.slice(0, 1), results: null, racePace: null, idealLaps: null });

  assert.deepEqual([card.finish, card.medianLapMs, card.idealLapMs], [null, null, null]);
});

test("drivers are grouped into teams in the order the session lists them", () => {
  const cards = teamCards({ drivers: DRIVERS, results: RESULTS, racePace: RACE_PACE, idealLaps: null });

  assert.deepEqual(
    cards.map((card) => [card.id, card.name, card.color, card.drivers.map((driver) => driver.code)]),
    [
      ["mercedes", "Mercedes", "#00D7B6", ["RUS", "ANT"]],
      ["red-bull", "Red Bull", "#4781D7", ["VER"]]
    ]
  );
  assert.deepEqual(
    cards.map((card) => [card.points, card.bestFinish, card.paceLaps]),
    [
      [35, 1, 118],
      [18, 2, 0]
    ]
  );
});

test("a team with no classification has no points and no best finish, not zero and P99", () => {
  const noResults = teamCards({ drivers: DRIVERS, results: null, racePace: null, idealLaps: null });
  assert.deepEqual(
    noResults.map((card) => [card.points, card.bestFinish, card.paceLaps]),
    [
      [null, null, null],
      [null, null, null]
    ]
  );

  // A classification that leaves one team out: its points are a true zero,
  // and it has no finish to call its best.
  const partial = teamCards({ drivers: DRIVERS, results: RESULTS.slice(0, 1), racePace: null, idealLaps: null });
  assert.deepEqual([partial[1].points, partial[1].bestFinish], [0, null]);
});

// ---------------------------------------------------------------------------
// Telemetry
// ---------------------------------------------------------------------------

const lap = (driver, number) => ({
  driver_code: driver,
  lap_number: number,
  path: `telemetry/${driver.toLowerCase()}-lap-${number}.json`
});

test("the comparison starts on the first lap and the first lap of another driver", () => {
  const laps = [lap("ALB", 1), lap("ALB", 2), lap("ANT", 1), lap("ANT", 2)];

  assert.deepEqual(defaultTelemetryLaps(laps), { a: laps[0], b: laps[2] });
});

test("one driver's laps are compared with each other, and one lap with nothing", () => {
  const laps = [lap("ALB", 1), lap("ALB", 2)];

  assert.deepEqual(defaultTelemetryLaps(laps), { a: laps[0], b: laps[1] });
  assert.equal(defaultTelemetryLaps([lap("ALB", 1)]), null);
  assert.equal(defaultTelemetryLaps([]), null);
});

const sample = (distance, speed, time) => ({ distance_m: distance, speed_kph: speed, relative_time_ms: time });

function telemetryView() {
  return viewOf({
    "telemetry/index.json": { laps: [lap("RUS", 5), lap("VER", 7)] },
    "telemetry/rus-lap-5.json": [sample(0, 200, 0), sample(100, 250, 1500)],
    "telemetry/ver-lap-7.json": [sample(0, 190, 0), sample(100, 240, 1600)],
    "laps.json": [
      { session_id: "s", driver_code: "RUS", lap_number: 5, lap_time_ms: 68000, compound: "HARD" },
      { session_id: "s", driver_code: "VER", lap_number: 7, lap_time_ms: 68200, compound: "MEDIUM" }
    ],
    "drivers.json": DRIVERS
  });
}

test("two laps are compared from the files of the pinned view", async () => {
  const view = telemetryView();

  const comparison = await telemetryComparerOf(view)("RUS", 5, "VER", 7);

  assert.equal(comparison.driver_a.driver_code, "RUS");
  assert.equal(comparison.driver_a.lap_time_ms, 68000);
  assert.equal(comparison.driver_b.team, "Red Bull");
  assert.deepEqual(comparison.speed_a, [200, 250]);
  assert.deepEqual(comparison.speed_b, [190, 240]);
  assert.deepEqual(comparison.delta_time_ms, [0, 100]);
  // Paths inside the generation, with no session id in them: the view is the session.
  assert.deepEqual([...view.reads].sort(), [
    "drivers.json",
    "laps.json",
    "telemetry/index.json",
    "telemetry/rus-lap-5.json",
    "telemetry/ver-lap-7.json"
  ]);
});

test("a view without telemetry compares to an explanation, not an error", async () => {
  const view = viewOf({ "drivers.json": DRIVERS });

  const comparison = await telemetryComparerOf(view)("RUS", 5, "VER", 7);

  assert.match(comparison.reason, /No telemetry lap artifacts/);
  assert.deepEqual(view.reads, []);
});

test("a lap file that fails to load fails the comparison", async () => {
  const view = telemetryView();
  const comparer = telemetryComparerOf({
    ...view,
    read: async (path) => {
      if (path === "telemetry/ver-lap-7.json") {
        throw new PublishedDataError("generation_gone", "The generation is gone.", {});
      }
      return view.read(path);
    }
  });

  await assert.rejects(() => comparer("RUS", 5, "VER", 7), (error) => error.code === "generation_gone");
});

// ---------------------------------------------------------------------------
// Sharing one request
// ---------------------------------------------------------------------------

test("callers that ask at the same moment share one request", async () => {
  let calls = 0;
  let release;
  const load = shareWhilePending(() => {
    calls += 1;
    return new Promise((resolve) => {
      release = () => resolve(`answer ${calls}`);
    });
  });

  const first = load();
  const second = load();
  assert.equal(calls, 1);
  release();

  assert.deepEqual(await Promise.all([first, second]), ["answer 1", "answer 1"]);
});

test("nothing is kept once the request settles", async () => {
  let calls = 0;
  const load = shareWhilePending(async () => {
    calls += 1;
    return calls;
  });

  assert.equal(await load(), 1);
  // A later caller gets a fresh request, so how long an answer may be reused
  // is left to the HTTP cache.
  assert.equal(await load(), 2);
});

test("a failed request fails every caller that shared it, and the next one asks again", async () => {
  let calls = 0;
  const load = shareWhilePending(async () => {
    calls += 1;
    if (calls === 1) {
      throw new Error("offline");
    }
    return "back";
  });

  const [first, second] = await Promise.allSettled([load(), load()]);
  assert.equal(first.status, "rejected");
  assert.equal(second.status, "rejected");
  assert.equal(calls, 1);

  assert.equal(await load(), "back");
});
