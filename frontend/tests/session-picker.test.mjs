import assert from "node:assert/strict";
import test from "node:test";

import { pickerKeyForQuery, pickerSelection, pickerYears } from "../src/lib/session-picker.ts";
import { fixtureIndex, indexOf, meeting, sampleIndex, session } from "./support/sample-index.mjs";

const query = (text) => new URLSearchParams(text);

test("the picker offers published sessions only, as seasons of events of sessions", () => {
  assert.deepEqual(
    pickerYears(sampleIndex()).map((year) => [
      year.year,
      year.key,
      year.events.map((event) => [event.label, event.key, event.sessions.map((item) => item.label)])
    ]),
    [
      [
        2026,
        11315,
        [
          ["R7 · Barcelona Grand Prix", 11300, ["R · Race (partial)"]],
          ["R8 · Austrian Grand Prix", 11315, ["S · Sprint", "R · Race"]],
          ["Imola Grand Prix · not in the calendar", 11200, ["R · Race"]]
        ]
      ],
      [2025, 9001, [["R24 · Abu Dhabi Grand Prix", 9001, ["R · Race"]]]]
    ]
  );
});

test("a calendar with nothing published offers nothing and selects nothing", () => {
  const index = indexOf([
    { year: 2026, meetings: [meeting(1, "First", "2026-03-08", [session("R", "Race", "2026-03-08T04:00:00Z")])] }
  ]);

  assert.deepEqual(pickerYears(index), []);
  assert.equal(pickerSelection(pickerYears(index), null), null);
  assert.equal(pickerSelection(pickerYears(index), 11315), null);
});

test("with no key the picker selects the most recent published session", () => {
  const selection = pickerSelection(pickerYears(sampleIndex()), null);

  assert.equal(selection.year.year, 2026);
  assert.equal(selection.event.label, "R8 · Austrian Grand Prix");
  assert.equal(selection.session.key, 11315);
});

test("a key selects its session, its event and its season", () => {
  const years = pickerYears(sampleIndex());

  const sprint = pickerSelection(years, 11314);
  assert.equal(sprint.session.label, "S · Sprint");
  assert.equal(sprint.event.key, 11315);

  const unplaced = pickerSelection(years, 11200);
  assert.equal(unplaced.event.label, "Imola Grand Prix · not in the calendar");
  assert.equal(unplaced.year.year, 2026);

  assert.equal(pickerSelection(years, 9001).year.year, 2025);
});

test("a key the picker does not offer falls back to the most recent session", () => {
  assert.equal(pickerSelection(pickerYears(sampleIndex()), 123456).session.key, 11315);
});

test("choosing a season or an event is choosing a session of it", () => {
  const years = pickerYears(sampleIndex());
  const season2025 = years.find((year) => year.year === 2025);
  const barcelona = years[0].events[0];

  // What the picker stores when the reader picks a season or an event is the
  // key each carries, and that key selects the season or event back.
  assert.equal(pickerSelection(years, season2025.key).year.year, 2025);
  assert.equal(pickerSelection(years, barcelona.key).event.label, "R7 · Barcelona Grand Prix");
});

test("the selection follows a session through a calendar change", () => {
  // The picker holds key 11315. The calendar then gains a race at round 8 and
  // Austria becomes round 9: the selection is still Austria, under its new
  // round, where a held round 8 would now be the inserted race (AR-20).
  const after = indexOf([
    {
      year: 2026,
      meetings: [
        meeting(8, "Inserted Grand Prix", "2026-06-21", [
          session("R", "Race", "2026-06-21T13:00:00Z", { session_key: 11400, complete: true })
        ]),
        meeting(9, "Austrian Grand Prix", "2026-06-28", [
          session("R", "Race", "2026-06-28T13:00:00Z", { session_key: 11315, complete: true })
        ])
      ]
    }
  ]);

  assert.equal(pickerSelection(pickerYears(sampleIndex()), 11315).event.label, "R8 · Austrian Grand Prix");
  assert.equal(pickerSelection(pickerYears(after), 11315).event.label, "R9 · Austrian Grand Prix");
});

test("the picker starts on the session the address names by key", () => {
  const index = sampleIndex();

  assert.equal(pickerKeyForQuery(index, query("key=11314")), 11314);
  assert.equal(pickerKeyForQuery(index, query("key=11200")), 11200);
  // A key that is well formed and not published selects nothing in particular.
  assert.equal(pickerKeyForQuery(index, query("key=4")), null);
  assert.equal(pickerKeyForQuery(index, query("key=abc")), null);
});

test("a key wins over a round given beside it, as it does on the session page", () => {
  const index = sampleIndex();

  // The round in this address is Barcelona's; the key is the Austrian sprint's.
  assert.equal(pickerKeyForQuery(index, query("key=11314&year=2026&round=7&session=R")), 11314);
  // A key that is not one leaves the address to its year, round and type.
  assert.equal(pickerKeyForQuery(index, query("key=abc&year=2026&round=7&session=R")), 11300);
});

test("the picker starts on the session an address names by year, round and type", () => {
  const index = sampleIndex();

  assert.equal(pickerKeyForQuery(index, query("year=2026&round=8&session=S")), 11314);
  assert.equal(pickerKeyForQuery(index, query("year=2026&round=8&session=r")), 11315);
  // Not published: the picker goes to the meeting it belongs to.
  assert.equal(pickerKeyForQuery(index, query("year=2026&round=8&session=Q")), 11315);
});

test("the picker starts on the meeting or the season an address names", () => {
  const index = sampleIndex();

  assert.equal(pickerKeyForQuery(index, query("year=2026&round=7")), 11300);
  assert.equal(pickerKeyForQuery(index, query("year=2025")), 9001);
  // A meeting with nothing published leaves the picker on its season.
  assert.equal(pickerKeyForQuery(index, query("year=2026&round=9")), 11315);
  assert.equal(pickerKeyForQuery(index, query("year=2031")), null);
  assert.equal(pickerKeyForQuery(index, query("")), null);
});

test("the published fixture gives the picker one season, one event and one session", () => {
  const years = pickerYears(fixtureIndex());

  assert.deepEqual(
    years.map((year) => [year.year, year.events.map((event) => [event.label, event.sessions])]),
    [[2026, [["R8 · Austrian Grand Prix", [{ key: 11315, label: "R · Race" }]]]]]
  );
  assert.equal(pickerKeyForQuery(fixtureIndex(), query("year=2026&round=8&session=R")), 11315);
});

// On /meeting the key is the meeting's (routes.ts). The picker read
// `/meeting?key=1288` as a session key, found none, and showed the latest race.
test("on a meeting's page the key is the meeting's, and the picker starts on its latest session", () => {
  const index = sampleIndex();

  assert.equal(pickerKeyForQuery(index, query("key=1288"), "/meeting/"), 11315);
  assert.equal(pickerKeyForQuery(index, query("key=1287"), "/meeting"), 11300);
  // A meeting the picker does not offer, and a session's key, name no meeting here.
  assert.equal(pickerKeyForQuery(index, query("key=1289"), "/meeting/"), null);
  assert.equal(pickerKeyForQuery(index, query("key=11314"), "/meeting/"), null);
  // By year and round as before.
  assert.equal(pickerKeyForQuery(index, query("year=2026&round=7"), "/meeting/"), 11300);
  // Anywhere else a key is a session's.
  assert.equal(pickerKeyForQuery(index, query("key=1288"), "/session/"), null);
  assert.equal(pickerKeyForQuery(index, query("key=11314"), "/strategy/"), 11314);
});
