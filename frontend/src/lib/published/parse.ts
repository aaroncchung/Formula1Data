/**
 * Validation of what is published outside a generation: the index, a
 * session's pointer, a generation's manifest and a season's standings.
 *
 * Each parser takes parsed JSON of unknown shape and returns the typed,
 * frozen value, or throws a PublishedDataError. Nothing is read from a
 * payload that has not been checked first, because a page that renders a
 * half-understood pointer shows wrong data with no sign that it is wrong.
 */

import {
  FORMAT_VERSION,
  INDEX_SCHEMA_VERSION,
  POINTER_SCHEMA_VERSION,
  STANDINGS_SCHEMA_VERSION
} from "./config.ts";
import { PublishedDataError } from "./errors.ts";
import type { PublishedErrorCode } from "./errors.ts";
import { isArtifactPath, isGenerationId, isSessionKey } from "./layout.ts";
import type {
  ConstructorStanding,
  Coverage,
  DriverStanding,
  IndexMeeting,
  IndexSeason,
  IndexSession,
  Manifest,
  Pointer,
  PublishedIndex,
  SessionIdentity,
  Standings,
  UnscheduledSession
} from "./types.ts";

type Fields = Record<string, unknown>;

/** Why a payload does not have its published shape. Callers of this module see a PublishedDataError. */
class Malformed extends Error {}

/**
 * The pointer of the session that was asked for.
 *
 * A pointer that exists and fails here is a fault, and must not be reported
 * as "not published": that would hide a broken publication behind a normal
 * state (rule 3). The checks are the publisher's own (`Pointer.from_json`).
 */
export function parsePointer(payload: unknown, sessionKey: number): Pointer {
  return parsed("invalid_pointer", `The pointer of session ${sessionKey}`, { session_key: sessionKey }, () => {
    const source = record(payload, "the pointer");
    const schemaVersion = integer(source, "schema_version");
    if (schemaVersion !== POINTER_SCHEMA_VERSION) {
      throw new Malformed(`schema_version is ${schemaVersion}, and this site reads ${POINTER_SCHEMA_VERSION}`);
    }
    // Before the fields the format governs: a pointer in another format may
    // lay them out differently, and "the site is older than the data" is the
    // true thing to say about it.
    const formatVersion = integer(source, "format_version");
    requireFormat("pointer", formatVersion);

    const key = integer(source, "session_key");
    if (key !== sessionKey) {
      throw new Malformed(`it is the pointer of session ${key}`);
    }
    const identity = parseIdentity(source.identity);
    if (identity.session_key !== key) {
      throw new Malformed(`its identity is that of session ${identity.session_key}`);
    }
    const generation = source.generation;
    if (!isGenerationId(generation)) {
      throw new Malformed("generation is not 64 lowercase hex characters");
    }
    // A generation is named by its manifest's checksum, so a pointer whose
    // two halves disagree cannot be followed either way.
    const manifest = record(source.manifest, "manifest");
    const manifestSha256 = text(manifest, "sha256", "manifest");
    if (manifestSha256 !== generation) {
      throw new Malformed("generation and manifest.sha256 differ");
    }

    return {
      schema_version: schemaVersion,
      format_version: formatVersion,
      pipeline_version: integer(source, "pipeline_version"),
      session_key: key,
      identity,
      generation,
      manifest: { sha256: manifestSha256, size_bytes: integer(manifest, "size_bytes", "manifest") },
      snapshot_id: text(source, "snapshot_id"),
      classification_fingerprint: optionalText(source, "classification_fingerprint"),
      coverage: parseCoverage(source.coverage),
      published_at: text(source, "published_at"),
      previous_generation: optionalText(source, "previous_generation")
    };
  });
}

/**
 * The manifest of the generation a view pinned. Its `schema_version` is the
 * artifact format version: most artifacts carry no version of their own, so
 * this is the one place the format of everything in the generation is checked
 * (rule 7).
 */
export function parseManifest(payload: unknown, sessionKey: number): Manifest {
  return parsed("invalid_manifest", `The manifest of session ${sessionKey}`, { session_key: sessionKey }, () => {
    const source = record(payload, "the manifest");
    const formatVersion = integer(source, "schema_version");
    requireFormat("manifest", formatVersion);

    const key = integer(source, "session_key");
    if (key !== sessionKey) {
      throw new Malformed(`it is the manifest of session ${key}`);
    }
    return {
      schema_version: formatVersion,
      pipeline_version: integer(source, "pipeline_version"),
      session_key: key,
      files: list(source, "files").map((item, index) => {
        const where = `files[${index}]`;
        const file = record(item, where);
        const path = file.path;
        if (!isArtifactPath(path)) {
          throw new Malformed(`${where}.path is not a path inside the generation`);
        }
        return { path, size_bytes: integer(file, "size_bytes", where), sha256: text(file, "sha256", where) };
      })
    };
  });
}

/** The calendar, with each published session attached to its entry. */
export function parseIndex(payload: unknown): PublishedIndex {
  return parsed("invalid_index", "The index of published data", {}, () => {
    const source = record(payload, "the index");
    const schemaVersion = integer(source, "schema_version");
    if (schemaVersion !== INDEX_SCHEMA_VERSION) {
      throw new Malformed(`schema_version is ${schemaVersion}, and this site reads ${INDEX_SCHEMA_VERSION}`);
    }
    const formatVersion = integer(source, "format_version");
    requireFormat("index", formatVersion);

    return {
      schema_version: schemaVersion,
      format_version: formatVersion,
      seasons: list(source, "seasons").map(parseSeason),
      unscheduled: list(source, "unscheduled").map(parseUnscheduled)
    };
  });
}

function parseSeason(value: unknown, index: number): IndexSeason {
  const where = `seasons[${index}]`;
  const source = record(value, where);
  return {
    year: integer(source, "year", where),
    meetings: list(source, "meetings", where).map((item, position) =>
      parseMeeting(item, `${where}.meetings[${position}]`)
    )
  };
}

function parseMeeting(value: unknown, where: string): IndexMeeting {
  const source = record(value, where);
  return {
    round: integer(source, "round", where),
    name: text(source, "name", where),
    official_name: optionalText(source, "official_name", where),
    country: optionalText(source, "country", where),
    location: optionalText(source, "location", where),
    date: optionalText(source, "date", where),
    format: optionalText(source, "format", where),
    sessions: list(source, "sessions", where).map((item, position) =>
      parseIndexSession(item, `${where}.sessions[${position}]`)
    )
  };
}

function parseIndexSession(value: unknown, where: string): IndexSession {
  const source = record(value, where);
  // The publisher adds `session_key` and `complete` only to a published
  // session (`derive_index`), so their absence is the "not published" state.
  const key = source.session_key ?? null;
  if (key !== null && !isSessionKey(key)) {
    throw new Malformed(`${where}.session_key is not a session key`);
  }
  return {
    type: text(source, "type", where),
    name: text(source, "name", where),
    start_time_utc: optionalText(source, "start_time_utc", where),
    session_key: key,
    complete: key === null ? null : flag(source, "complete", where)
  };
}

function parseUnscheduled(value: unknown, index: number): UnscheduledSession {
  const where = `unscheduled[${index}]`;
  const source = record(value, where);
  const key = source.session_key;
  if (!isSessionKey(key)) {
    throw new Malformed(`${where}.session_key is not a session key`);
  }
  return {
    session_key: key,
    year: integer(source, "year", where),
    type: text(source, "type", where),
    name: text(source, "name", where),
    meeting_name: text(source, "meeting_name", where),
    start_time_utc: text(source, "start_time_utc", where),
    complete: flag(source, "complete", where)
  };
}

/**
 * The standings of the season that was asked for. They are checked before
 * anything is read from them: a table that is half understood would be shown
 * as the championship with no sign that it is wrong. The rows keep the
 * published order and points, and nothing is added up (AR-15).
 */
export function parseStandings(payload: unknown, year: number): Standings {
  return parsed("invalid_standings", `The standings file for ${year}`, { year }, () => {
    const source = record(payload, "the standings");
    const schemaVersion = integer(source, "schema_version");
    if (schemaVersion !== STANDINGS_SCHEMA_VERSION) {
      throw new Malformed(`schema_version is ${schemaVersion}, and this site reads ${STANDINGS_SCHEMA_VERSION}`);
    }
    const formatVersion = integer(source, "format_version");
    requireFormat("standings", formatVersion);

    const found = integer(source, "year");
    if (found !== year) {
      throw new Malformed(`it holds the standings of ${found}`);
    }
    const rounds = record(source.rounds, "rounds");
    return {
      schema_version: schemaVersion,
      format_version: formatVersion,
      year: found,
      rounds: {
        drivers: integer(rounds, "drivers", "rounds"),
        constructors: integer(rounds, "constructors", "rounds")
      },
      drivers: list(source, "drivers").map(parseDriverStanding),
      constructors: list(source, "constructors").map(parseConstructorStanding)
    };
  });
}

/**
 * What Jolpica can leave out for a driver is null and the row is still read:
 * a driver it has not classified has no position, and an older season has
 * neither codes nor permanent numbers.
 */
function parseDriverStanding(value: unknown, index: number): DriverStanding {
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

function parseConstructorStanding(value: unknown, index: number): ConstructorStanding {
  const where = `constructors[${index}]`;
  const source = record(value, where);
  return {
    position: optionalInteger(source, "position", where),
    points: number(source, "points", where),
    wins: integer(source, "wins", where),
    constructor_id: optionalText(source, "constructor_id", where),
    name: text(source, "name", where)
  };
}

function parseIdentity(value: unknown): SessionIdentity {
  const where = "identity";
  const source = record(value, where);
  return {
    session_key: integer(source, "session_key", where),
    year: integer(source, "year", where),
    session_type: text(source, "session_type", where),
    session_name: text(source, "session_name", where),
    start_time_utc: text(source, "start_time_utc", where),
    meeting_name: text(source, "meeting_name", where),
    meeting_official_name: optionalText(source, "meeting_official_name", where),
    location: optionalText(source, "location", where),
    country: optionalText(source, "country", where),
    circuit_name: optionalText(source, "circuit_name", where)
  };
}

function parseCoverage(value: unknown): Coverage {
  const where = "coverage";
  const source = record(value, where);
  // The publisher's own reader accepts a pointer without the list
  // (`coverage.get("shortfalls") or []`), so this one does too.
  const shortfalls: unknown[] = source.shortfalls == null ? [] : list(source, "shortfalls", where);
  return {
    complete: flag(source, "complete", where),
    shortfalls: shortfalls.map((item, index) => {
      const at = `${where}.shortfalls[${index}]`;
      const shortfall = record(item, at);
      return {
        bar: text(shortfall, "bar", at),
        driver: optionalText(shortfall, "driver", at),
        detail: text(shortfall, "detail", at)
      };
    })
  };
}

/**
 * The frontend reads the one format it was built for (rule 7). Anything else
 * fails here, with which side is behind, instead of being rendered as if its
 * fields meant what this build thinks they mean.
 */
function requireFormat(object: "index" | "pointer" | "manifest" | "standings", found: number): void {
  if (found === FORMAT_VERSION) {
    return;
  }
  const site = found > FORMAT_VERSION ? "older" : "newer";
  const verb = object === "standings" ? "are" : "is";
  throw new PublishedDataError(
    "format_mismatch",
    `This site reads published data in format ${FORMAT_VERSION}, and the ${object} ${verb} in format ${found}: the site is ${site} than the data.`,
    { object, expected: FORMAT_VERSION, found, site }
  );
}

/** Build a value, freeze it, and report a shape fault under the caller's code. */
function parsed<T>(
  code: PublishedErrorCode,
  subject: string,
  details: Readonly<Record<string, unknown>>,
  build: () => T
): T {
  try {
    const value = build();
    freeze(value);
    return value;
  } catch (error) {
    if (error instanceof Malformed) {
      throw new PublishedDataError(code, `${subject} is invalid: ${error.message}.`, details);
    }
    throw error;
  }
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

function text(source: Fields, field: string, where?: string): string {
  const value = source[field];
  if (typeof value !== "string") {
    throw new Malformed(`${named(field, where)} is not a string`);
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

function integer(source: Fields, field: string, where?: string): number {
  const value = source[field];
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new Malformed(`${named(field, where)} is not an integer`);
  }
  return value;
}

function optionalInteger(source: Fields, field: string, where?: string): number | null {
  const value = source[field];
  return value === undefined || value === null ? null : integer(source, field, where);
}

/** A number that need not be whole: championship points can be halves. */
function number(source: Fields, field: string, where?: string): number {
  const value = source[field];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Malformed(`${named(field, where)} is not a number`);
  }
  return value;
}

function flag(source: Fields, field: string, where?: string): boolean {
  const value = source[field];
  if (typeof value !== "boolean") {
    throw new Malformed(`${named(field, where)} is not true or false`);
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
