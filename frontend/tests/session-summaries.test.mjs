import assert from "node:assert/strict";
import test from "node:test";

import { latestPublishedSession } from "../src/lib/calendar.ts";
import { PublishedDataError } from "../src/lib/published/errors.ts";
import { loadSessionByKey } from "../src/lib/published/session.ts";
import {
  driverCards,
  idealLapLeader,
  readField,
  readPaceAnalysis,
  readSessionFigures,
  teamCards
} from "../src/lib/session-summaries.ts";
import { shareWhilePending } from "../src/lib/shared-request.ts";
import {
  bucketOf,
  clientOf,
  FIRST_GENERATION,
  generationPrefix,
  INDEX_KEY,
  POINTER_KEY,
  republish,
  reversedResults,
  SESSION_KEY
} from "./support/published-bucket.mjs";

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

const driver = (code, name, number, driverTeam) => ({
  driver_id: code.toLowerCase(),
  code,
  full_name: name,
  number,
  country: null,
  team: driverTeam
});
const DRIVERS = [
  driver("RUS", "George Russell", 63, MERCEDES),
  driver("VER", "Max Verstappen", 3, RED_BULL),
  driver("ANT", "Andrea Kimi Antonelli", 12, MERCEDES)
];
const result = (position, code, points, fields = {}) => ({
  position,
  classified_position: String(position),
  driver_code: code,
  points,
  grid: position,
  laps: 71,
  status: "Finished",
  time_ms: null,
  gap_ms: null,
  laps_down: null,
  behind_at_flag_ms: null,
  provisional: false,
  ...fields
});
const RESULTS = [result(1, "RUS", 25), result(2, "VER", 18), result(5, "ANT", 10)];
const RACE_PACE = {
  drivers: [
    { driver_code: "RUS", median_lap_ms: 68100, lap_count: 60 },
    { driver_code: "ANT", median_lap_ms: 68350, lap_count: 58 }
  ],
  stints: [],
  caveats: []
};
const IDEAL_LAPS = { rows: [{ driver_code: "VER", ideal_lap_ms: 66900, delta_to_ideal_ms: 120 }] };

// ---------------------------------------------------------------------------
// Readers
// ---------------------------------------------------------------------------

test("the field is the drivers, with whatever else the generation holds beside them", async () => {
  const full = viewOf({
    "drivers.json": DRIVERS,
    "results.json": RESULTS,
    "analysis/race-pace.json": RACE_PACE,
    "analysis/ideal-laps.json": IDEAL_LAPS,
    "laps.json": [],
    "position-replay.json": []
  });
  assert.deepEqual(await readField(full), {
    drivers: DRIVERS,
    results: RESULTS,
    racePace: RACE_PACE,
    idealLaps: IDEAL_LAPS
  });
  // The page's own four files, and neither the laps nor the replay.
  assert.deepEqual([...full.reads].sort(), [
    "analysis/ideal-laps.json",
    "analysis/race-pace.json",
    "drivers.json",
    "results.json"
  ]);

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
    () => readField(viewOf({ "drivers.json": DRIVERS, "results.json": gone })),
    (error) => error.code === "generation_gone"
  );
});

test("a file of the wrong kind is invalid before a page maps over it, as it is for a tab", async () => {
  // The checks are the ones the session dashboard's tabs make: these pages
  // read every file through the same `ARTIFACTS`.
  const cases = [
    [() => readField(viewOf({ "drivers.json": { drivers: [] } })), /drivers\.json is not a list/],
    [() => readField(viewOf({ "drivers.json": DRIVERS, "results.json": "none" })), /results\.json is not a list/],
    [() => readPaceAnalysis(viewOf({ "analysis/race-pace.json": { drivers: null } })), /has no list of drivers/],
    [() => readSessionFigures(viewOf({ "analysis/ideal-laps.json": { rows: 3 } })), /has no list of rows/],
    [() => readSessionFigures(viewOf({ "summary.json": null })), /summary\.json is not an object/]
  ];

  for (const [read, message] of cases) {
    await assert.rejects(read, (error) => error.code === "invalid_artifact" && message.test(error.message), String(message));
  }
});

test("the home page's figures and chart are absent, with no request, when the generation has none", async () => {
  const view = viewOf({ "drivers.json": DRIVERS });

  assert.deepEqual(await readSessionFigures(view), { summary: null, idealLaps: null });
  assert.equal(await readPaceAnalysis(view), null);
  assert.deepEqual(view.reads, []);
});

test("the home page's chart reads the pace analysis and not the laps the race-pace tab reads", async () => {
  const view = viewOf({ "analysis/race-pace.json": RACE_PACE, "laps.json": [], "analysis/tyre-degradation.json": { rows: [] } });

  assert.deepEqual(await readPaceAnalysis(view), RACE_PACE);
  assert.deepEqual(view.reads, ["analysis/race-pace.json"]);
});

test("the most recent published session opens by its key, and a page's reads stay on its generation", async () => {
  // What the home page and a summary page with no session in its address do:
  // ask the calendar which session is the most recent, open it by its key
  // with the loader every session page uses, and read through the view.
  const bucket = bucketOf();
  const client = clientOf(bucket);

  const latest = latestPublishedSession(await client.index());
  assert.equal(latest.key, SESSION_KEY);
  const load = await loadSessionByKey(client, latest.key);

  assert.equal(load.status, "ready");
  assert.equal(load.heading.round, 8);
  assert.equal(load.view.pointer.generation, FIRST_GENERATION);
  assert.equal(bucket.count(POINTER_KEY), 1);

  // The session is published again while the page is open.
  republish(bucket, { "results.json": reversedResults() });
  bucket.requests.length = 0;

  const field = await readField(load.view);
  assert.equal(field.results[0].driver_code, "RUS");
  assert.deepEqual(await readSessionFigures(load.view), {
    summary: JSON.parse(bucket.stored.get(`${generationPrefix(FIRST_GENERATION)}summary.json`)),
    idealLaps: JSON.parse(bucket.stored.get(`${generationPrefix(FIRST_GENERATION)}analysis/ideal-laps.json`))
  });
  for (const key of bucket.keys()) {
    assert.ok(key.startsWith(generationPrefix(FIRST_GENERATION)), key);
  }
  assert.equal(bucket.count(INDEX_KEY), 0);
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

test("a driver the classification gives a letter has no finishing place, and the card shows the letter", () => {
  const retired = [RESULTS[0], result(19, "VER", 0, { classified_position: "R", status: "Retired" })];

  const cards = driverCards({ drivers: DRIVERS, results: retired, racePace: null, idealLaps: null });

  assert.deepEqual(
    cards.map((card) => [card.driver.code, card.finish, card.classification]),
    [
      ["RUS", 1, "1"],
      ["VER", null, "R"],
      ["ANT", null, null]
    ]
  );
  // The retirement is not the team's best finish, and it is not a 19th place.
  const teams = teamCards({ drivers: DRIVERS, results: retired, racePace: null, idealLaps: null });
  assert.deepEqual(teams.map((card) => [card.id, card.bestFinish]), [["mercedes", 1], ["red-bull", null]]);
});

test("a provisional order gives places and no points", () => {
  const provisional = RESULTS.map((row) => ({ ...row, classified_position: null, points: null, provisional: true }));

  const teams = teamCards({ drivers: DRIVERS, results: provisional, racePace: null, idealLaps: null });

  assert.deepEqual(teams.map((card) => [card.id, card.points, card.bestFinish]), [
    ["mercedes", null, 1],
    ["red-bull", null, 2]
  ]);
});

// With no classification the result is the order on track. A card gave it
// out as each driver's finish, the car that never left the grid included.
test("a provisional order is told as one, and a car that completed no lap has no place in it", () => {
  const provisional = RESULTS.map((row, index) => ({
    ...row,
    classified_position: null,
    points: null,
    provisional: true,
    laps: index === RESULTS.length - 1 ? 0 : 57
  }));
  const last = provisional.at(-1);
  const field = { drivers: DRIVERS, results: provisional, racePace: null, idealLaps: null };

  const cards = driverCards(field);

  const ran = cards.find((card) => card.driver.code === provisional[0].driver_code);
  assert.deepEqual([ran.finish, ran.provisional], [provisional[0].position, true]);
  const neverRan = cards.find((card) => card.driver.code === last.driver_code);
  assert.deepEqual([neverRan.finish, neverRan.classification], [null, null]);
  const teams = teamCards(field);
  assert.equal(teams.every((card) => card.provisional), true);
  assert.equal(teams.some((card) => card.bestFinish === last.position), false);
  // A classification says so of itself, and its places are places.
  assert.equal(driverCards({ ...field, results: RESULTS }).some((card) => card.provisional), false);
  assert.equal(teamCards({ ...field, results: RESULTS }).some((card) => card.provisional), false);
});

test("drivers F1's list names no team for are shown together, not left out", () => {
  const drivers = [...DRIVERS, driver("DOO", "Jack Doohan", 7, null), driver("COL", "Franco Colapinto", 43, null)];

  const teams = teamCards({ drivers, results: null, racePace: null, idealLaps: null });

  assert.deepEqual(
    teams.map((card) => [card.name, card.color, card.drivers.map((item) => item.code)]),
    [
      ["Mercedes", "#00D7B6", ["RUS", "ANT"]],
      ["Red Bull", "#4781D7", ["VER"]],
      ["No team listed", null, ["DOO", "COL"]]
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

test("the ideal-lap card names the leader, and says when a figure is missing rather than printing nought", () => {
  const row = (driver, delta) => ({
    driver_code: driver,
    ideal_lap_ms: 65000,
    best_lap_ms: 65200,
    best_sector_1_ms: 17000,
    best_sector_2_ms: 30000,
    best_sector_3_ms: 18000,
    delta_to_ideal_ms: delta
  });
  const laps = (rows) => ({ rows, caveats: [] });

  assert.deepEqual(idealLapLeader(laps([row("PIA", 212.4), row("NOR", 80)])), {
    value: "PIA",
    detail: "0.212s left on track"
  });
  // A null was printed as "0.000s left on track".
  assert.deepEqual(idealLapLeader(laps([row("PIA", null)])), { value: "PIA", detail: "Time left on track not published" });
  // With no ideal laps the card showed the session's weather under its label.
  assert.deepEqual(idealLapLeader(laps([])), { value: "--", detail: "No driver has a time in every sector" });
  assert.deepEqual(idealLapLeader(null), { value: "--", detail: "Not published for this session" });
});
