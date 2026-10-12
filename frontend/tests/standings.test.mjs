import assert from "node:assert/strict";
import test from "node:test";

import { standingsKey } from "../src/lib/published/layout.ts";
import { parseStandings } from "../src/lib/published/parse.ts";
import {
  defaultStandingsYear,
  driverName,
  figureLabel,
  roundLabel,
  standingsRounds,
  winsLabel
} from "../src/lib/standings-view.ts";
import { BASE_URL, bucketOf, clientOf, edit, failureOf, PUBLISHED } from "./support/published-bucket.mjs";
import { fixtureIndex, indexOf, meeting, sampleIndex, session } from "./support/sample-index.mjs";

// The shape f1data/standings.py writes (`fetch_standings`). The figures are
// the ones AR-15 found the old page got wrong: it showed ANT with 158 points
// against an official 179, and HAM ahead of RUS.
const STANDINGS = {
  schema_version: 1,
  format_version: 2,
  year: 2026,
  rounds: { drivers: 9, constructors: 9 },
  drivers: [
    {
      position: 1,
      points: 179,
      wins: 4,
      driver_code: "ANT",
      driver_number: 12,
      given_name: "Andrea Kimi",
      family_name: "Antonelli",
      constructors: ["Mercedes"]
    },
    {
      position: 2,
      points: 154,
      wins: 2,
      driver_code: "RUS",
      driver_number: 63,
      given_name: "George",
      family_name: "Russell",
      constructors: ["Mercedes"]
    },
    {
      position: 3,
      points: 147.5,
      wins: 1,
      driver_code: "HAM",
      driver_number: 44,
      given_name: "Lewis",
      family_name: "Hamilton",
      constructors: ["Ferrari"]
    }
  ],
  constructors: [
    { position: 1, points: 333, wins: 6, constructor_id: "mercedes", name: "Mercedes" },
    { position: 2, points: 260.5, wins: 1, constructor_id: "ferrari", name: "Ferrari" }
  ]
};

const KEY = "v2/standings/2026.json";

function publishedWith(standings = STANDINGS) {
  return bucketOf({ [KEY]: JSON.stringify(standings) });
}

function changed(change) {
  const copy = structuredClone(STANDINGS);
  change(copy);
  return copy;
}

// ---------------------------------------------------------------------------
// Reading
// ---------------------------------------------------------------------------

test("the standings are read from their own key and shown as published", async () => {
  const bucket = publishedWith();

  const standings = await clientOf(bucket).standings(2026);

  assert.deepEqual(bucket.keys(), [KEY]);
  assert.equal(standingsKey(2026), KEY);
  assert.deepEqual(standings, STANDINGS);
});

test("the published order and points are kept, not worked out again", async () => {
  // Jolpica's order is the championship's. A reader that sorted by points
  // would undo a tie-break or a position Jolpica set for another reason.
  const reordered = changed((value) => {
    value.drivers.reverse();
  });

  const standings = await clientOf(publishedWith(reordered)).standings(2026);

  assert.deepEqual(
    standings.drivers.map((row) => [row.driver_code, row.position, row.points]),
    [
      ["HAM", 3, 147.5],
      ["RUS", 2, 154],
      ["ANT", 1, 179]
    ]
  );
});

test("standings that are not published are null, not a failure", async () => {
  const bucket = bucketOf({});

  assert.equal(await clientOf(bucket).standings(2026), null);
  assert.deepEqual(bucket.keys(), [KEY]);
});

test("an outage is not shown as a season without standings", async () => {
  const offline = publishedWith();
  offline.fault = () => new TypeError("Failed to fetch");
  const failure = await failureOf(clientOf(offline).standings(2026));
  assert.equal(failure.code, "unavailable");
  assert.match(failure.message, /Failed to fetch/);

  const broken = publishedWith();
  broken.fault = () => new Response("upstream error", { status: 502 });
  const badGateway = await failureOf(clientOf(broken).standings(2026));
  assert.equal(badGateway.code, "unavailable");
  assert.equal(badGateway.details.status, 502);
});

test("a reader with no base URL says so and makes no request", async () => {
  const bucket = publishedWith();

  const failure = await failureOf(clientOf(bucket, { baseUrl: "" }).standings(2026));

  assert.equal(failure.code, "not_configured");
  assert.deepEqual(bucket.keys(), []);
});

test("a base URL with a trailing slash reads the same key", async () => {
  const bucket = publishedWith();

  await clientOf(bucket, { baseUrl: `${BASE_URL}/` }).standings(2026);

  assert.deepEqual(bucket.keys(), [KEY]);
});

test("a season that is not a year is refused before any request", async () => {
  const bucket = publishedWith();

  await assert.rejects(() => clientOf(bucket).standings(Number.NaN), RangeError);
  await assert.rejects(() => clientOf(bucket).standings(2026.5), RangeError);
  assert.deepEqual(bucket.keys(), []);
});

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

test("standings that are not JSON are invalid, not missing", async () => {
  const bucket = bucketOf({ [KEY]: "<html>not found</html>" });

  const failure = await failureOf(clientOf(bucket).standings(2026));

  assert.equal(failure.code, "invalid_standings");
  assert.match(failure.message, /standings file for 2026 is not JSON/);
});

test("standings in another format say which side is behind", async () => {
  const newer = await failureOf(
    clientOf(publishedWith(changed((value) => { value.format_version = 3; }))).standings(2026)
  );
  assert.equal(newer.code, "format_mismatch");
  assert.equal(newer.details.site, "older");
  assert.equal(newer.details.object, "standings");

  // What `v1/standings/` held: the same tables, in format 1.
  const older = await failureOf(
    clientOf(publishedWith(changed((value) => { value.format_version = 1; }))).standings(2026)
  );
  assert.equal(older.code, "format_mismatch");
  assert.deepEqual(older.details, { object: "standings", expected: 2, found: 1, site: "newer" });
  assert.match(older.message, /newer than the data/);
});

test("the standings the publisher writes are read as they are", async () => {
  const standings = await clientOf(bucketOf()).standings(2026);

  assert.deepEqual(standings, JSON.parse(PUBLISHED[KEY]));
  assert.equal(standings.constructors[0].points, 556.5);
});

test("standings with another schema version are not read", async () => {
  const failure = await failureOf(
    clientOf(publishedWith(changed((value) => { value.schema_version = 2; }))).standings(2026)
  );

  assert.equal(failure.code, "invalid_standings");
  assert.match(failure.message, /schema_version is 2, and this site reads 1/);
});

test("standings filed under another season are a fault", () => {
  assert.throws(() => parseStandings(STANDINGS, 2025), /it holds the standings of 2026/);
});

test("each field the page shows is checked before the table is trusted", () => {
  const cases = [
    [(value) => { value.drivers = {}; }, /drivers is not a list/],
    [(value) => { value.constructors = null; }, /constructors is not a list/],
    [(value) => { delete value.rounds; }, /rounds is not an object/],
    [(value) => { value.rounds.drivers = "9"; }, /rounds\.drivers is not an integer/],
    [(value) => { value.drivers[1].points = "154"; }, /drivers\[1\]\.points is neither a number nor null/],
    [(value) => { value.drivers[2].wins = 1.5; }, /drivers\[2\]\.wins is not an integer/],
    [(value) => { value.constructors[0].wins = "6"; }, /constructors\[0\]\.wins is not an integer/],
    [(value) => { value.drivers[0].constructors = "Mercedes"; }, /drivers\[0\]\.constructors is not a list/],
    [(value) => { value.drivers[0].constructors = [7]; }, /drivers\[0\]\.constructors\[0\] is not a string/],
    [(value) => { value.drivers[0].driver_code = 12; }, /drivers\[0\]\.driver_code is neither a string nor null/],
    [(value) => { value.constructors[1].name = 7; }, /constructors\[1\]\.name is neither a string nor null/],
    [(value) => { value.constructors[0] = "Mercedes"; }, /constructors\[0\] is not an object/]
  ];

  for (const [change, message] of cases) {
    assert.throws(
      () => parseStandings(changed(change), 2026),
      (error) => error.code === "invalid_standings" && message.test(error.message),
      String(message)
    );
  }
  assert.throws(() => parseStandings([], 2026), /the standings is not an object/);
});

test("what Jolpica leaves out of a row is null, and the row is still read", () => {
  // A driver Jolpica has not classified has no position, and an older season
  // has neither codes nor permanent numbers. A figure it leaves out stays
  // absent: it is not read as zero points or no wins.
  const sparse = changed((value) => {
    value.drivers[2] = {
      position: null,
      points: null,
      wins: null,
      driver_code: null,
      driver_number: null,
      given_name: null,
      family_name: "Hamilton",
      constructors: []
    };
    value.constructors[1] = { constructor_id: null, position: null, points: null, wins: null, name: null };
  });

  const standings = parseStandings(sparse, 2026);

  assert.deepEqual(standings.drivers[2], sparse.drivers[2]);
  assert.deepEqual(standings.constructors[1], sparse.constructors[1]);
  assert.equal(driverName(standings.drivers[2]), "Hamilton");
});

test("a figure the standings leave out is shown as absent, never as zero", () => {
  assert.equal(figureLabel(null), "--");
  assert.equal(figureLabel(0), "0");
  assert.equal(figureLabel(236.5), "236.5");
  assert.equal(winsLabel(null), "-- wins");
  assert.equal(winsLabel(0), "0 wins");
  assert.equal(winsLabel(1), "1 win");
  assert.equal(winsLabel(11), "11 wins");
});

test("parsed standings cannot be changed by the page that shows them", () => {
  const standings = parseStandings(structuredClone(STANDINGS), 2026);

  assert.throws(() => { standings.drivers[0].points = 0; }, TypeError);
  assert.throws(() => { standings.drivers.push(standings.drivers[0]); }, TypeError);
  assert.throws(() => { standings.rounds.drivers = 1; }, TypeError);
});

test("a correction that does not advance the round is read on the next visit", async () => {
  // Done-when 2: nothing is kept between reads, so a penalty applied after
  // the race changes the table without the round or the site changing.
  const bucket = publishedWith();
  const client = clientOf(bucket);
  assert.equal((await client.standings(2026)).drivers[1].points, 154);

  edit(bucket, KEY, (value) => {
    value.drivers[1].points = 151;
  });

  const corrected = await client.standings(2026);
  assert.equal(corrected.drivers[1].points, 151);
  assert.equal(corrected.rounds.drivers, 9);
  assert.equal(bucket.count(KEY), 2);
});

// ---------------------------------------------------------------------------
// Which round the tables are after
// ---------------------------------------------------------------------------

test("the round the standings are after is named from the calendar", () => {
  const season = sampleIndex().seasons.find((item) => item.year === 2026);
  const standings = parseStandings(changed((value) => { value.rounds = { drivers: 8, constructors: 8 }; }), 2026);

  const rounds = standingsRounds(standings, season);

  assert.deepEqual(rounds.drivers, { round: 8, meetingName: "Austrian Grand Prix", of: 3 });
  assert.equal(rounds.agree, true);
  assert.equal(roundLabel(rounds.drivers), "After round 8 of 3 · Austrian Grand Prix");
});

test("the round is still stated when the calendar has no meeting there, or is not at hand", () => {
  const standings = parseStandings(structuredClone(STANDINGS), 2026);
  const season = sampleIndex().seasons.find((item) => item.year === 2026);

  assert.equal(roundLabel(standingsRounds(standings, season).drivers), "After round 9 of 3 · British Grand Prix");
  assert.equal(roundLabel(standingsRounds(standings, null).drivers), "After round 9");
  assert.equal(
    roundLabel(standingsRounds(parseStandings(changed((value) => { value.rounds.drivers = 20; }), 2026), season).drivers),
    "After round 20 of 3"
  );
});

test("two tables a round apart are reported as such", () => {
  // The two tables are two requests to Jolpica; for a moment after a race one
  // has the new round and the other has not.
  const standings = parseStandings(changed((value) => { value.rounds = { drivers: 9, constructors: 8 }; }), 2026);

  const rounds = standingsRounds(standings, null);

  assert.equal(rounds.agree, false);
  assert.equal(rounds.drivers.round, 9);
  assert.equal(rounds.constructors.round, 8);
});

test("the page opens on the newest season that has started, not on one that is only scheduled", () => {
  const race = (published) =>
    meeting(1, "First Grand Prix", "2026-03-08", [session("R", "Race", "2026-03-08T04:00:00Z", published)]);
  const nextYearListed = indexOf([
    { year: 2026, meetings: [race({ session_key: 1, complete: true })] },
    { year: 2027, meetings: [race()] }
  ]);

  assert.equal(defaultStandingsYear(nextYearListed), 2026);
  assert.equal(defaultStandingsYear(sampleIndex()), 2026);
  assert.equal(defaultStandingsYear(fixtureIndex()), 2026);
});

test("with nothing published the page opens on the newest season, and on none when there is none", () => {
  const unpublished = indexOf([
    { year: 2025, meetings: [] },
    { year: 2026, meetings: [meeting(1, "First Grand Prix", "2026-03-08", [session("R", "Race", null)])] }
  ]);

  assert.equal(defaultStandingsYear(unpublished), 2026);
  assert.equal(defaultStandingsYear(indexOf([])), null);
});

test("a driver is named in full", () => {
  assert.equal(driverName(STANDINGS.drivers[0]), "Andrea Kimi Antonelli");
});
