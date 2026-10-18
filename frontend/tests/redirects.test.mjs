import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import test from "node:test";

import { parseSessionAddress, sessionQuery } from "../src/lib/published/lookup.ts";
import { meetingChoice, meetingQuery, yearParam } from "../src/lib/routes.ts";

// The file Cloudflare Pages reads from the root of the export, which Next
// copies there from public/.
const REDIRECTS = readFileSync(new URL("../public/_redirects", import.meta.url), "utf8");
const APP = new URL("../src/app/", import.meta.url);

/** Each rule as Pages reads it: one per line, `source destination code`, and lines starting with `#` ignored. */
function rules() {
  return REDIRECTS.split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "" && !line.startsWith("#"))
    .map((line) => {
      const [source, destination, code, ...rest] = line.split(/\s+/);
      assert.deepEqual(rest, [], line);
      return { line, source, destination, code: Number(code) };
    });
}

/** The paths the export has a page at, with and without the trailing slash it adds. */
function exportedPaths() {
  const paths = ["/"];
  for (const entry of readdirSync(APP, { withFileTypes: true })) {
    if (entry.isDirectory() && existsSync(new URL(`${entry.name}/page.tsx`, APP))) {
      paths.push(`/${entry.name}`, `/${entry.name}/`);
    }
  }
  return paths;
}

const OLD_PATH = /^\/seasons\/([0-9]{4})(?:\/([0-9]{1,2})(?:\/([A-Z0-9]+))?)?\/?$/;

/** What a destination opens, read by the readers the pages themselves use. */
function opened(destination) {
  const url = new URL(destination, "https://site.example");
  // Straight to the exported file: the export adds a trailing slash, and a
  // path without one would be sent on by a second redirect.
  if (url.pathname === "/session/") {
    const address = parseSessionAddress(url.searchParams);
    assert.ok(address, destination);
    assert.equal(url.search, `?${sessionQuery(address)}`, destination);
    return { page: "session", address };
  }
  if (url.pathname === "/meeting/") {
    const choice = meetingChoice(url.searchParams);
    assert.equal(choice.kind, "named", destination);
    assert.equal(url.search, `?${meetingQuery(choice.address)}`, destination);
    return { page: "meeting", address: choice.address };
  }
  if (url.pathname === "/season/") {
    const year = yearParam(url.searchParams);
    assert.equal(year.status, "ok", destination);
    assert.equal(url.search, `?year=${year.value}`, destination);
    return { page: "season", year: year.value };
  }
  assert.equal(destination, "/", destination);
  return { page: "home" };
}

test("every rule is one Pages reads, and none of them is dynamic", () => {
  const all = rules();

  assert.ok(all.length > 0);
  // Pages takes at most 2,000 static rules, and its placeholders and splats
  // match more than the old pages: see the next test.
  assert.ok(all.length <= 2000);
  for (const rule of all) {
    assert.ok([301, 302].includes(rule.code), rule.line);
    assert.doesNotMatch(rule.source, /[:*]/, rule.line);
    assert.match(rule.source, /^\/[^?#]*$/, rule.line);
  }
  const sources = all.map((rule) => rule.source);
  assert.equal(new Set(sources).size, sources.length, "a source is listed twice, and only the first would apply");
});

test("no rule takes a page the site still has", () => {
  const sources = new Set(rules().map((rule) => rule.source));

  for (const path of exportedPaths()) {
    assert.ok(!sources.has(path), path);
  }
  // The list of seasons is still a page, and the files beside it are what
  // the router fetches to open it.
  assert.ok(exportedPaths().includes("/seasons/"));
  for (const source of sources) {
    assert.ok(source === "/live" || source === "/live/" || source === "/settings" || source === "/settings/" || OLD_PATH.test(source), source);
  }
});

test("every old address opens the same season, meeting or race on a page that reads it", () => {
  for (const rule of rules()) {
    const target = opened(rule.destination);
    const old = OLD_PATH.exec(rule.source);
    if (!old) {
      // The pages that were removed go to the home page, and not for good.
      assert.deepEqual(target, { page: "home" }, rule.line);
      assert.equal(rule.code, 302, rule.line);
      continue;
    }
    const [, year, round, type] = old;
    if (type) {
      // A race goes by its key, which stays with it.
      assert.equal(target.page, "session", rule.line);
      assert.equal(target.address.kind, "key", rule.line);
      assert.equal(rule.code, 301, rule.line);
    } else if (round) {
      assert.equal(target.page, "meeting", rule.line);
      if (target.address.kind === "key") {
        assert.equal(rule.code, 301, rule.line);
      } else {
        // By a round, which is today's and may move: not for good.
        assert.equal(target.address.year, Number(year), rule.line);
        assert.equal(rule.code, 302, rule.line);
      }
    } else {
      assert.deepEqual(target, { page: "season", year: Number(year) }, rule.line);
      assert.equal(rule.code, 301, rule.line);
    }
  }
});

test("each old address is there with and without its trailing slash, going to the same place", () => {
  const bySource = new Map(rules().map((rule) => [rule.source, rule]));

  for (const [source, rule] of bySource) {
    const other = source.endsWith("/") ? source.slice(0, -1) : `${source}/`;
    assert.ok(bySource.has(other), `${source} has no rule for ${other}`);
    assert.equal(bySource.get(other).destination, rule.destination, source);
    assert.equal(bySource.get(other).code, rule.code, source);
  }
});

// The old site's pages, from its catalog: two seasons, the 46 meetings of
// their calendars and the 33 races it had data for. A link to any of them
// still opens what it showed.
test("the old site's pages are all there, and a few land where they should", () => {
  const sources = new Set(rules().map((rule) => rule.source));
  const destination = (source) => rules().find((rule) => rule.source === source)?.destination;

  const old = [...sources].filter((source) => OLD_PATH.test(source) && source.endsWith("/"));
  assert.equal(old.filter((source) => source.split("/").length === 4).length, 2);
  assert.equal(old.filter((source) => source.split("/").length === 5).length, 46);
  assert.equal(old.filter((source) => source.split("/").length === 6).length, 33);

  assert.equal(destination("/seasons/2026/8/R/"), "/session/?key=11315");
  assert.equal(destination("/seasons/2025/1/R"), "/session/?key=9693");
  assert.equal(destination("/seasons/2026/8/"), "/meeting/?key=1288");
  // The old site's round 16 of 2026 was Singapore, round 17 since Bahrain was added.
  assert.equal(destination("/seasons/2026/16/"), "/meeting/?year=2026&round=17");
  assert.equal(destination("/seasons/2026"), "/season/?year=2026");
});
