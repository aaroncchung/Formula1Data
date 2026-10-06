/**
 * The championship standings of one season, as the publisher took them from
 * Jolpica (f1data/standings.py is the source of truth for the shape).
 *
 * The site used to add up points over the sessions it held, which was wrong
 * for 12 of 22 drivers on 2026-10-05: sprints were missing, and a result
 * corrected after a race was never picked up (AR-15). Nothing here adds
 * anything up. The table is shown as published, with the round it is after.
 *
 * Standings are one object per season that is rewritten in place, like the
 * index, so they are read fresh on every visit and never through a session's
 * generation.
 */

import type { PublishedClientOptions, PublishedFetch } from "./client.ts";
import { FORMAT_VERSION } from "./config.ts";
import { PublishedDataError } from "./errors.ts";

// Mirrors STANDINGS_SCHEMA_VERSION in f1data/standings.py.
export const STANDINGS_SCHEMA_VERSION = 1;

const DEFAULT_TIMEOUT_MS = 30_000;

export type DriverStanding = {
  /** Null when Jolpica lists the driver without a classified position. */
  readonly position: number | null;
  readonly points: number;
  readonly wins: number;
  readonly driver_code: string | null;
  readonly driver_number: number | null;
  readonly given_name: string | null;
  readonly family_name: string | null;
  /** Every constructor the driver has entered for this season, in Jolpica's order. */
  readonly constructors: ReadonlyArray<string>;
};

export type ConstructorStanding = {
  readonly position: number | null;
  readonly points: number;
  readonly wins: number;
  readonly constructor_id: string | null;
  readonly name: string;
};

export type Standings = {
  readonly schema_version: number;
  readonly format_version: number;
  readonly year: number;
  /**
   * The round each table is after. They are two requests to Jolpica and can be
   * a round apart for a moment, so a page states each and never assumes one.
   */
  readonly rounds: { readonly drivers: number; readonly constructors: number };
  readonly drivers: ReadonlyArray<DriverStanding>;
  readonly constructors: ReadonlyArray<ConstructorStanding>;
};

export type StandingsReader = {
  /**
   * The standings of `year`, or null when none are published. Null is a normal
   * state: before a season's first round Jolpica has no table and the
   * publisher writes nothing. An outage or a broken file throws instead, so
   * neither is ever shown as "no standings yet".
   */
  read(year: number): Promise<Standings | null>;
};

export function standingsKey(year: number): string {
  return `v${FORMAT_VERSION}/standings/${year}.json`;
}

/**
 * A reader of `v1/standings/<year>.json`.
 *
 * It makes its own request instead of going through `createPublishedClient`,
 * whose one GET is private to it. The rule is the same and must stay the same:
 * only a 404 means "absent", and anything else that goes wrong says nothing
 * about what exists.
 */
export function createStandingsReader(options: PublishedClientOptions): StandingsReader {
  // Held as a plain function: a browser's `fetch` throws when it is called
  // with a receiver other than the global object.
  const { fetch: request, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const base = options.baseUrl.replace(/\/+$/, "");

  async function read(year: number): Promise<Standings | null> {
    if (!Number.isSafeInteger(year) || year < 0) {
      throw new RangeError(`Not a season: ${String(year)}`);
    }
    if (!base) {
      throw new PublishedDataError("not_configured", "No base URL for published data is configured.");
    }
    const url = `${base}/${standingsKey(year).split("/").map(encodeURIComponent).join("/")}`;
    const text = await get(request, url, timeoutMs);
    if (text === null) {
      return null;
    }
    let payload: unknown;
    try {
      payload = JSON.parse(text);
    } catch {
      throw new PublishedDataError("invalid_artifact", `The standings of ${year} are not JSON.`, { url, year });
    }
    return parseStandings(payload, year);
  }

  return Object.freeze({ read });
}

/** The body of a 2xx answer, or null for a 404. */
async function get(request: PublishedFetch, url: string, timeoutMs: number): Promise<string | null> {
  let response: Awaited<ReturnType<PublishedFetch>>;
  try {
    response = await request(url, { signal: AbortSignal.timeout(timeoutMs) });
  } catch (error) {
    throw unreachable(url, error);
  }
  if (response.status === 404) {
    return null;
  }
  if (response.status < 200 || response.status > 299) {
    throw new PublishedDataError("unavailable", `${url} answered ${response.status}.`, {
      url,
      status: response.status
    });
  }
  try {
    return await response.text();
  } catch (error) {
    throw unreachable(url, error);
  }
}

function unreachable(url: string, cause: unknown): PublishedDataError {
  const reason = cause instanceof Error ? cause.message : String(cause);
  return new PublishedDataError("unavailable", `${url} could not be read: ${reason}`, { url, reason });
}

type Fields = Record<string, unknown>;

/** Why a payload does not have the published shape. Callers see a PublishedDataError. */
class Malformed extends Error {}

/**
 * The standings that were asked for, checked before anything is read from
 * them. A table that is half understood would be shown as the championship
 * with no sign that it is wrong, which is the fault this page exists to end.
 */
export function parseStandings(payload: unknown, year: number): Standings {
  try {
    const source = record(payload, "the standings");
    const schemaVersion = integer(source, "schema_version");
    if (schemaVersion !== STANDINGS_SCHEMA_VERSION) {
      throw new Malformed(`schema_version is ${schemaVersion}, and this site reads ${STANDINGS_SCHEMA_VERSION}`);
    }
    // Before the fields the format governs, as for the index and the pointer:
    // "the site is older than the data" is the true thing to say about a
    // table in another format.
    const formatVersion = integer(source, "format_version");
    if (formatVersion !== FORMAT_VERSION) {
      const site = formatVersion > FORMAT_VERSION ? "older" : "newer";
      throw new PublishedDataError(
        "format_mismatch",
        `This site reads published data in format ${FORMAT_VERSION}, and the standings are in format ${formatVersion}: the site is ${site} than the data.`,
        { object: "standings", expected: FORMAT_VERSION, found: formatVersion, site }
      );
    }
    const found = integer(source, "year");
    if (found !== year) {
      throw new Malformed(`they are the standings of ${found}`);
    }
    const rounds = record(source.rounds, "rounds");
    const standings: Standings = {
      schema_version: schemaVersion,
      format_version: formatVersion,
      year: found,
      rounds: {
        drivers: integer(rounds, "drivers", "rounds"),
        constructors: integer(rounds, "constructors", "rounds")
      },
      drivers: list(source, "drivers").map(parseDriver),
      constructors: list(source, "constructors").map(parseConstructor)
    };
    freeze(standings);
    return standings;
  } catch (error) {
    if (error instanceof Malformed) {
      throw new PublishedDataError("invalid_artifact", `The standings of ${year} are invalid: ${error.message}.`, {
        year
      });
    }
    throw error;
  }
}

function parseDriver(value: unknown, index: number): DriverStanding {
  const where = `drivers[${index}]`;
  const source = record(value, where);
  return {
    position: optionalInteger(source, "position", where),
    points: number(source, "points", where),
    wins: integer(source, "wins", where),
    driver_code: optionalText(source, "driver_code", where),
    driver_number: optionalInteger(source, "driver_number", where),
    given_name: optionalText(source, "given_name", where),
    family_name: optionalText(source, "family_name", where),
    constructors: list(source, "constructors", where).map((name, position) => {
      if (typeof name !== "string") {
        throw new Malformed(`${where}.constructors[${position}] is not a string`);
      }
      return name;
    })
  };
}

function parseConstructor(value: unknown, index: number): ConstructorStanding {
  const where = `constructors[${index}]`;
  const source = record(value, where);
  const name = source.name;
  if (typeof name !== "string") {
    throw new Malformed(`${where}.name is not a string`);
  }
  return {
    position: optionalInteger(source, "position", where),
    points: number(source, "points", where),
    wins: integer(source, "wins", where),
    constructor_id: optionalText(source, "constructor_id", where),
    name
  };
}

function freeze(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(freeze);
    Object.freeze(value);
  } else if (isRecord(value)) {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
}

function isRecord(value: unknown): value is Fields {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, where: string): Fields {
  if (!isRecord(value)) {
    throw new Malformed(`${where} is not an object`);
  }
  return value;
}

function named(field: string, where?: string): string {
  return where ? `${where}.${field}` : field;
}

function integer(source: Fields, field: string, where?: string): number {
  const value = source[field];
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new Malformed(`${named(field, where)} is not an integer`);
  }
  return value;
}

function optionalInteger(source: Fields, field: string, where?: string): number | null {
  const value = source[field];
  if (value === undefined || value === null) {
    return null;
  }
  return integer(source, field, where);
}

/** Points can be halves, so they are a number and not an integer. */
function number(source: Fields, field: string, where?: string): number {
  const value = source[field];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Malformed(`${named(field, where)} is not a number`);
  }
  return value;
}

function optionalText(source: Fields, field: string, where?: string): string | null {
  const value = source[field];
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "string") {
    throw new Malformed(`${named(field, where)} is neither a string nor null`);
  }
  return value;
}

function list(source: Fields, field: string, where?: string): unknown[] {
  const value: unknown = source[field];
  if (!Array.isArray(value)) {
    throw new Malformed(`${named(field, where)} is not a list`);
  }
  return value;
}
