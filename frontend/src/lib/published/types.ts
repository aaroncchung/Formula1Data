/**
 * What the reader hands on of the objects it validates in full: the index, a
 * session's pointer, a generation's manifest and a season's standings.
 *
 * Every type here is derived from the generated ones in schema.ts, which are
 * the published schema, so the reader cannot describe a field the format does
 * not have, or miss one it gains: parse.ts builds these values field by
 * field, and a field that changed in the schema stops it compiling. The few
 * places the reader is deliberately narrower or wider than the schema are
 * spelled out below, each with its reason.
 *
 * Everything is read-only, and frozen at runtime, so that nothing a page does
 * can change which generation a view reads. The files of a generation are
 * not validated field by field and are not frozen; their types are used
 * straight from schema.ts (see artifacts.ts).
 */

import type * as Schema from "./schema.ts";

/** The same shape with every level read-only. */
export type DeepReadonly<T> = T extends ReadonlyArray<infer Item>
  ? ReadonlyArray<DeepReadonly<Item>>
  : T extends object
    ? { readonly [Key in keyof T]: DeepReadonly<T[Key]> }
    : T;

/**
 * Who a session is, independent of where it sits in the calendar.
 *
 * The schema's identity also has `round_at_fetch` and `archive_path`. Both
 * are left out on purpose. The round a page shows comes from the current
 * index, and a second, older round within reach would sooner or later be used
 * as identity (rule 5); the archive path is the publisher's.
 *
 * `session_type` is read as text, not as the schema's list of session codes.
 * It is only shown and matched, and a code this build has not heard of should
 * not make it refuse a session it can otherwise read.
 */
export type SessionIdentity = DeepReadonly<
  Omit<Schema.Identity, "round_at_fetch" | "archive_path" | "session_type"> & { session_type: string }
>;

/**
 * One bar a session fell short of when it was fetched. `driver` is null for a
 * session-wide feed. `bar` is read as text for the same reason as a session's
 * type: the publisher adds a bar when it learns to measure something new.
 */
export type Shortfall = DeepReadonly<Omit<Schema.Shortfall, "bar"> & { bar: string }>;

/** A session's verdict in its pointer. `coverage.json` in the generation has the figures behind it. */
export type PointerCoverage = DeepReadonly<Omit<Schema.PointerCoverage, "shortfalls">> & {
  readonly shortfalls: ReadonlyArray<Shortfall>;
};

/**
 * `also` and `record` are the publisher's own bookkeeping, by which it knows
 * when to build a session again. A page has no use for either, and `also`
 * holds a round, so neither is read.
 */
export type Pointer = DeepReadonly<Omit<Schema.Pointer, "also" | "record" | "identity" | "coverage">> & {
  readonly identity: SessionIdentity;
  readonly coverage: PointerCoverage;
};

export type ManifestFile = DeepReadonly<Schema.ManifestFile>;

/** The manifest repeats the session's identity; the reader takes it from the pointer, which it read first. */
export type Manifest = DeepReadonly<Omit<Schema.Manifest, "identity">>;

/**
 * A session of the calendar. `session_key` and `complete` are there only once
 * it is published, and the key is the identity; the round is not. `in_scope`
 * says whether the publisher covers this kind of session at all, which tells
 * a session that is not published yet from one that never will be.
 */
export type IndexSession = DeepReadonly<Omit<Schema.IndexSession, "type"> & { type: string }>;

/** A calendar session that is published: it has a key and a coverage verdict. */
export type PublishedIndexSession = IndexSession & { readonly session_key: number; readonly complete: boolean };

/**
 * `round` is where the meeting sits in the calendar of this index, and can
 * differ in the next one. `meeting_key` does not move, and is known once one
 * of the meeting's sessions is published.
 */
export type IndexMeeting = DeepReadonly<Omit<Schema.IndexMeeting, "sessions">> & {
  readonly sessions: ReadonlyArray<IndexSession>;
};

export type IndexSeason = { readonly year: number; readonly meetings: ReadonlyArray<IndexMeeting> };

/** A published session the current calendar has no entry for. */
export type UnscheduledSession = DeepReadonly<Omit<Schema.UnscheduledSession, "type"> & { type: string }>;

export type PublishedIndex = DeepReadonly<Omit<Schema.Index, "seasons" | "unscheduled">> & {
  readonly seasons: ReadonlyArray<IndexSeason>;
  readonly unscheduled: ReadonlyArray<UnscheduledSession>;
};

export type DriverStanding = DeepReadonly<Schema.DriverStanding>;
export type ConstructorStanding = DeepReadonly<Schema.ConstructorStanding>;

/**
 * The championship standings of one season, as the publisher took them from
 * Jolpica. They are shown as published: the site used to add up points over
 * the sessions it held, which was wrong for 12 of 22 drivers (AR-15).
 *
 * `rounds` is the round each table is after. They are two requests to Jolpica
 * and can be a round apart for a moment, so a page states each and never
 * assumes one.
 */
export type Standings = DeepReadonly<Schema.Standings>;
