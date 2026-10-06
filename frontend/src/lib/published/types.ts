/**
 * The published shapes, as the reader hands them on after validating them.
 * The source of truth is f1data/publish.py (`Pointer`, `build_manifest`,
 * `derive_index`); tests/fixtures/published-v1.json holds one of each.
 *
 * Everything is read-only, and frozen at runtime, so that nothing a page does
 * can change which generation a view reads.
 */

/**
 * Who a session is, independent of where it sits in the calendar. The
 * publisher also records `round_at_fetch`; it is left out on purpose, because
 * the round a page shows comes from the current index and a second, older
 * round within reach would sooner or later be used as identity (rule 5).
 */
export type SessionIdentity = {
  readonly session_key: number;
  readonly year: number;
  readonly session_type: string;
  readonly session_name: string;
  readonly start_time_utc: string;
  readonly meeting_name: string;
  readonly meeting_official_name: string | null;
  readonly location: string | null;
  readonly country: string | null;
  readonly circuit_name: string | null;
};

/** One bar a session fell short of when it was fetched. `driver` is null for a session-wide feed. */
export type Shortfall = {
  readonly bar: string;
  readonly driver: string | null;
  readonly detail: string;
};

export type Coverage = {
  readonly complete: boolean;
  readonly shortfalls: ReadonlyArray<Shortfall>;
};

export type Pointer = {
  readonly schema_version: number;
  readonly format_version: number;
  readonly pipeline_version: number;
  readonly session_key: number;
  readonly identity: SessionIdentity;
  /** Always equal to `manifest.sha256`. */
  readonly generation: string;
  readonly manifest: { readonly sha256: string; readonly size_bytes: number };
  readonly snapshot_id: string;
  readonly classification_fingerprint: string | null;
  readonly coverage: Coverage;
  readonly published_at: string;
  readonly previous_generation: string | null;
};

export type ManifestFile = {
  readonly path: string;
  readonly size_bytes: number;
  readonly sha256: string;
};

export type Manifest = {
  /** The artifact format version, not a version of the manifest itself. */
  readonly schema_version: number;
  readonly pipeline_version: number;
  readonly session_key: number;
  readonly files: ReadonlyArray<ManifestFile>;
};

export type IndexSession = {
  /** The short code: `FP1`, `Q`, `S`, `R`, and so on. */
  readonly type: string;
  readonly name: string;
  readonly start_time_utc: string | null;
  /** Set only when the session is published. This is the identity; the round is not. */
  readonly session_key: number | null;
  /** The pointer's coverage verdict when the index was derived; null when not published. */
  readonly complete: boolean | null;
};

export type IndexMeeting = {
  /** Where the meeting sits in the calendar of this index. It can differ in the next one. */
  readonly round: number;
  readonly name: string;
  readonly official_name: string | null;
  readonly country: string | null;
  readonly location: string | null;
  readonly date: string | null;
  readonly format: string | null;
  readonly sessions: ReadonlyArray<IndexSession>;
};

export type IndexSeason = {
  readonly year: number;
  readonly meetings: ReadonlyArray<IndexMeeting>;
};

/** A published session the current calendar has no entry for. */
export type UnscheduledSession = {
  readonly session_key: number;
  readonly year: number;
  readonly type: string;
  readonly name: string;
  readonly meeting_name: string;
  readonly start_time_utc: string;
  readonly complete: boolean;
};

export type PublishedIndex = {
  readonly schema_version: number;
  readonly format_version: number;
  readonly seasons: ReadonlyArray<IndexSeason>;
  readonly unscheduled: ReadonlyArray<UnscheduledSession>;
};
