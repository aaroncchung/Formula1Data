import assert from "node:assert/strict";
import test from "node:test";

import {
  assignDriverStyles,
  driverStyle,
  FALLBACK_DRIVER_COLOR,
  teamColorByDriver,
  teamDriverStyles
} from "../src/lib/driver-style.ts";

// The 2026 field as published in sessions/2026-08-r/drivers.json, in the
// order that file lists it (classification order, not team order).
const FIELD_2026 = [
  ["RUS", "#00D7B6"], ["VER", "#4781D7"], ["ANT", "#00D7B6"], ["PIA", "#F47600"],
  ["HAM", "#ED1131"], ["HAD", "#4781D7"], ["NOR", "#F47600"], ["LEC", "#ED1131"],
  ["LAW", "#6C98FF"], ["LIN", "#6C98FF"], ["BOR", "#F50537"], ["HUL", "#F50537"],
  ["GAS", "#00A1E8"], ["BEA", "#9C9FA2"], ["COL", "#00A1E8"], ["OCO", "#9C9FA2"],
  ["ALB", "#1868DB"], ["ALO", "#229971"], ["STR", "#229971"], ["SAI", "#1868DB"],
  ["PER", "#909090"], ["BOT", "#909090"]
].map(([code, color]) => ({ code, color }));

/** What a reader can actually see of a line: its colour and its pattern. */
function appearance(style) {
  return `${style.color}|${style.dash ?? "solid"}`;
}

test("team-mates keep the team colour and differ by line pattern", () => {
  const styles = assignDriverStyles([
    { code: "RUS", color: "#00D7B6" },
    { code: "ANT", color: "#00D7B6" }
  ]);
  const ant = driverStyle(styles, "ANT");
  const rus = driverStyle(styles, "RUS");

  assert.equal(ant.color, rus.color);
  assert.equal(ant.dash, undefined);
  assert.equal(typeof rus.dash, "string");
  assert.notEqual(ant.dash, rus.dash);
});

test("team-mates differ by marker fill as well, for charts that draw points", () => {
  const styles = assignDriverStyles([
    { code: "RUS", color: "#00D7B6" },
    { code: "ANT", color: "#00D7B6" }
  ]);

  assert.equal(driverStyle(styles, "ANT").hollow, false);
  assert.equal(driverStyle(styles, "RUS").hollow, true);
});

test("which team-mate is dashed does not depend on the order the data lists them in", () => {
  const listed = assignDriverStyles([
    { code: "RUS", color: "#00D7B6" },
    { code: "ANT", color: "#00D7B6" }
  ]);
  const reversed = assignDriverStyles([
    { code: "ANT", color: "#00D7B6" },
    { code: "RUS", color: "#00D7B6" }
  ]);

  assert.deepEqual(driverStyle(listed, "RUS"), driverStyle(reversed, "RUS"));
  assert.deepEqual(driverStyle(listed, "ANT"), driverStyle(reversed, "ANT"));
});

test("a driver alone in a colour is drawn solid and filled", () => {
  const styles = assignDriverStyles([
    { code: "VER", color: "#4781D7" },
    { code: "HAM", color: "#ED1131" }
  ]);

  for (const code of ["VER", "HAM"]) {
    assert.deepEqual(
      { dash: driverStyle(styles, code).dash, hollow: driverStyle(styles, code).hollow },
      { dash: undefined, hollow: false }
    );
  }
});

test("no two drivers of the 2026 field look the same", () => {
  const styles = assignDriverStyles(FIELD_2026);
  const appearances = FIELD_2026.map((driver) => appearance(driverStyle(styles, driver.code)));

  assert.equal(styles.size, 22);
  assert.equal(new Set(appearances).size, 22);
  assert.equal(appearances.filter((value) => value.endsWith("|solid")).length, 11);
});

test("colours that differ only in case or spacing are the same colour", () => {
  const styles = assignDriverStyles([
    { code: "RUS", color: "#00D7B6" },
    { code: "ANT", color: " #00d7b6 " }
  ]);

  assert.equal(driverStyle(styles, "ANT").color, driverStyle(styles, "RUS").color);
  assert.notEqual(driverStyle(styles, "ANT").dash, driverStyle(styles, "RUS").dash);
});

test("drivers without a colour share the fallback and are still told apart", () => {
  const styles = assignDriverStyles([
    { code: "AAA", color: null },
    { code: "BBB" },
    { code: "CCC", color: "" }
  ]);
  const appearances = ["AAA", "BBB", "CCC"].map((code) => appearance(driverStyle(styles, code)));

  assert.ok(["AAA", "BBB", "CCC"].every((code) => driverStyle(styles, code).color === FALLBACK_DRIVER_COLOR));
  assert.equal(new Set(appearances).size, 3);
});

test("two teams with one colour are separated like team-mates", () => {
  const styles = assignDriverStyles([
    { code: "AAA", color: "#909090" },
    { code: "BBB", color: "#909090" },
    { code: "CCC", color: "#909090" },
    { code: "DDD", color: "#909090" }
  ]);
  const appearances = ["AAA", "BBB", "CCC", "DDD"].map((code) => appearance(driverStyle(styles, code)));

  assert.equal(new Set(appearances).size, 4);
});

test("a driver listed twice is styled once", () => {
  const styles = assignDriverStyles([
    { code: "RUS", color: "#00D7B6" },
    { code: "RUS", color: "#00D7B6" },
    { code: "ANT", color: "#00D7B6" }
  ]);

  assert.equal(styles.size, 2);
  assert.equal(driverStyle(styles, "RUS").variant, 1);
});

test("a driver the styles do not cover is drawn plain grey, not left out", () => {
  const styles = assignDriverStyles([{ code: "RUS", color: "#00D7B6" }]);

  assert.deepEqual(driverStyle(styles, "ZZZ"), {
    color: FALLBACK_DRIVER_COLOR,
    variant: 0,
    dash: undefined,
    hollow: false
  });
});

test("styles for a session's drivers come from the team colour", () => {
  const drivers = [
    { code: "RUS", team: { color: "#00D7B6" } },
    { code: "ANT", team: { color: "#00D7B6" } },
    { code: "VER", team: { color: null } }
  ];
  const styles = teamDriverStyles(drivers);

  assert.equal(driverStyle(styles, "RUS").color, "#00d7b6");
  assert.equal(typeof driverStyle(styles, "RUS").dash, "string");
  assert.equal(driverStyle(styles, "VER").color, FALLBACK_DRIVER_COLOR);
  assert.deepEqual(teamColorByDriver(drivers), { RUS: "#00D7B6", ANT: "#00D7B6", VER: null });
});

const MERCEDES = [
  { code: "RUS", team: { color: "#00D7B6" } },
  { code: "ANT", team: { color: "#00D7B6" } }
];

test("a driver a chart has data for but the session does not list is styled too", () => {
  const styles = teamDriverStyles(MERCEDES, [{ code: "DOO", color: "#00A1E8" }]);

  assert.deepEqual(driverStyle(styles, "DOO"), { color: "#00a1e8", variant: 0, dash: undefined, hollow: false });
});

// A chart must not redraw the listed drivers because its own data names an
// extra one: "AAA" sorts before both Mercedes drivers and shares their colour.
test("an unlisted driver never changes how a listed driver looks", () => {
  const listedOnly = teamDriverStyles(MERCEDES);
  const withExtra = teamDriverStyles(MERCEDES, [{ code: "AAA", color: "#00D7B6" }]);

  assert.deepEqual(driverStyle(withExtra, "ANT"), driverStyle(listedOnly, "ANT"));
  assert.deepEqual(driverStyle(withExtra, "RUS"), driverStyle(listedOnly, "RUS"));
  assert.equal(driverStyle(withExtra, "AAA").variant, 2);
});

test("a listed driver keeps the team colour when a chart's own data disagrees", () => {
  const styles = teamDriverStyles(MERCEDES, [{ code: "RUS", color: "#ff0000" }]);

  assert.equal(driverStyle(styles, "RUS").color, "#00d7b6");
  assert.equal(styles.size, 2);
});
