import assert from "node:assert/strict";
import test from "node:test";

import {
  hideAllDrivers,
  NO_HIDDEN_DRIVERS,
  selectionSummary,
  toggleDriver,
  visibleDrivers
} from "../src/lib/driver-selection.ts";

const FIELD = ["ALB", "ALO", "ANT", "BEA", "BOR", "BOT", "COL", "GAS", "HAD", "HAM", "HUL"];

test("a chart starts with every driver shown, however many there are", () => {
  assert.deepEqual(visibleDrivers(FIELD, NO_HIDDEN_DRIVERS), FIELD);
  assert.equal(selectionSummary(FIELD, NO_HIDDEN_DRIVERS), "All 11 drivers shown");
});

test("toggling a shown driver hides that driver only", () => {
  const hidden = toggleDriver(NO_HIDDEN_DRIVERS, "ANT");

  assert.deepEqual(
    visibleDrivers(FIELD, hidden),
    FIELD.filter((driver) => driver !== "ANT")
  );
});

test("toggling a hidden driver shows it again", () => {
  const hidden = toggleDriver(toggleDriver(NO_HIDDEN_DRIVERS, "ANT"), "ANT");

  assert.deepEqual(visibleDrivers(FIELD, hidden), FIELD);
});

test("toggling returns a new set and leaves the previous one alone", () => {
  const before = toggleDriver(NO_HIDDEN_DRIVERS, "ANT");
  const after = toggleDriver(before, "HAM");

  assert.notEqual(after, before);
  assert.deepEqual([...before], ["ANT"]);
  assert.equal(NO_HIDDEN_DRIVERS.size, 0);
});

test("hiding everything and picking two drivers focuses the chart on those two", () => {
  const hidden = toggleDriver(toggleDriver(hideAllDrivers(FIELD), "HAM"), "ALB");

  assert.deepEqual(visibleDrivers(FIELD, hidden), ["ALB", "HAM"]);
  assert.equal(selectionSummary(FIELD, hidden), "2 of 11 drivers shown");
});

test("the visible drivers keep the chart's order, not the order they were picked in", () => {
  const hidden = toggleDriver(toggleDriver(hideAllDrivers(FIELD), "HUL"), "ALO");

  assert.deepEqual(visibleDrivers(FIELD, hidden), ["ALO", "HUL"]);
});

test("the summary says so when drivers are hidden, down to none", () => {
  assert.equal(selectionSummary(FIELD, toggleDriver(NO_HIDDEN_DRIVERS, "ANT")), "10 of 11 drivers shown");
  assert.equal(selectionSummary(FIELD, hideAllDrivers(FIELD)), "0 of 11 drivers shown");
});

test("a hidden driver that is not in the data does not distort the count", () => {
  const hidden = toggleDriver(NO_HIDDEN_DRIVERS, "ZZZ");

  assert.deepEqual(visibleDrivers(FIELD, hidden), FIELD);
  assert.equal(selectionSummary(FIELD, hidden), "All 11 drivers shown");
});

test("the summary handles one driver and no drivers", () => {
  assert.equal(selectionSummary(["VER"], NO_HIDDEN_DRIVERS), "All 1 driver shown");
  assert.equal(selectionSummary([], NO_HIDDEN_DRIVERS), "No drivers in this data");
});
