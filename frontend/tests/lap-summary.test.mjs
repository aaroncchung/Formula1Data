import assert from "node:assert/strict";
import test from "node:test";

import { fastestLapByDriver } from "../src/lib/lap-summary.ts";

function lap(driver, number, time, overrides = {}) {
  return {
    session_id: "2026-08-r",
    driver_code: driver,
    lap_number: number,
    lap_time_ms: time,
    compound: "HARD",
    is_pit_in_lap: false,
    is_pit_out_lap: false,
    is_deleted: false,
    is_accurate: true,
    ...overrides
  };
}

test("each driver's fastest lap is listed once, quickest driver first", () => {
  const laps = [lap("RUS", 40, 70_900), lap("ANT", 61, 70_374), lap("RUS", 55, 70_512), lap("ANT", 12, 71_800)];

  assert.deepEqual(
    fastestLapByDriver(laps).map((row) => [row.driver_code, row.lap_number, row.lap_time_ms]),
    [
      ["ANT", 61, 70_374],
      ["RUS", 55, 70_512]
    ]
  );
});

test("a deleted or untimed lap is nobody's fastest lap", () => {
  const laps = [
    lap("VER", 30, 69_900, { is_deleted: true }),
    lap("VER", 31, 70_600),
    lap("BOT", 1, null),
    lap("BOT", 2, 0),
    lap("PER", 3, undefined)
  ];

  assert.deepEqual(
    fastestLapByDriver(laps).map((row) => [row.driver_code, row.lap_number]),
    [["VER", 31]]
  );
});

test("of two equal laps the one set first is kept, and equal drivers are listed by code", () => {
  const laps = [lap("VER", 20, 70_000), lap("VER", 10, 70_000), lap("VER", 30, 70_000), lap("ALB", 5, 70_000)];

  assert.deepEqual(
    fastestLapByDriver(laps).map((row) => [row.driver_code, row.lap_number]),
    [
      ["ALB", 5],
      ["VER", 10]
    ]
  );
});
