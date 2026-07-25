# Code review findings

Full-codebase review performed 2026-07-25 against branch `fix/persist-fastf1-cache`
(HEAD `fc5203e`). Scope: `worker/`, `pipeline/`, `backend/`, `frontend/`,
`.github/workflows/`, `migrations/`, and root configuration.

Test suites were run locally at review time:

| Suite | Command | Result |
| --- | --- | --- |
| Worker | `node --test "worker/tests/*.test.mjs"` | 31 passed, 0 failed |
| Python | `python backend/tests/test_*.py` | 46 passed, 8 skipped (pandas absent locally), 1 file failed to import |

Findings are ordered by severity. Each entry names the observable failure, the
code that causes it, and the direction of a fix. Nothing in this document has
been changed in the code yet.

---

## High severity

### H1. Bulk-queued ingestion jobs are silently cancelled by GitHub Actions concurrency

- **Where:** `.github/workflows/process-ingestion-job.yml:21-23`
- **Related:** `.github/workflows/schedule-ingestion.yml:16-18`, `pipeline/schedule_ingestion.py:88-104`, `worker/src/index.mjs:178-188`

`process-ingestion-job.yml` declares `concurrency: { group: ingestion,
cancel-in-progress: false }`. GitHub Actions permits only **one pending run per
concurrency group** — when a new run is queued, any previously pending run in
that group is cancelled outright.

`schedule-ingestion.yml` runs hourly and `pipeline.schedule_ingestion` POSTs one
ingestion request per session (up to 7 session codes per meeting). The Worker
turns each into its own `repository_dispatch`. With one run executing and one
pending, every additional dispatch evicts the previously pending run.

Consequence: most queued sessions are never ingested. Their D1 jobs stay
`queued`/`running` until `reconcileStaleIngestionJobs` fails them 120 minutes
later with `Ingestion did not complete within 120 minutes` — a message that
points at FastF1 rather than at the real cause, which makes this expensive to
diagnose from the logs.

**Direction:** make the concurrency group per-session (for example
`ingestion-${{ github.event.client_payload.message.session_id }}`), or replace
the per-job dispatch with a single draining runner that processes the queue in
one workflow run.

---

### H2. Re-ingesting a session that already has committed artifacts never updates the R2 indexes

- **Where:** `pipeline/local_queue_worker.py:101-104`, `pipeline/local_queue_worker.py:160-168`

`process_message` has two publication paths:

- **Fresh ingestion** (lines 113-158): builds into a temp dir, calls
  `merge_incremental_indexes`, then `publish_artifacts` → `sync_artifacts_to_r2`
  with `include_indexes` defaulting to `True`. Correct.
- **Reuse** (lines 101-104, 160-168), taken whenever
  `frontend/public/data/sessions/<id>/manifest.json` exists in the checkout —
  true for all 33 committed sessions: calls `sync_artifacts_to_r2(...,
  include_indexes=False)` and never calls `merge_incremental_indexes` at all.

On the reuse path the session's own files are uploaded to R2, but `catalog.json`
and `seasons/<year>.json` are not. The job reports `succeeded` while the session
remains absent from any UI that reads the R2 catalog.

The reuse behaviour itself is intentional and documented (`README.md:212`); the
index omission is the defect.

**Direction:** run the index merge and marker upload on both paths. The reuse
path already has `output_dir` as its publication dir, so it needs the same
`merge_incremental_indexes` + `include_indexes=True` treatment.

---

### H3. The first ingestion into an empty R2 bucket always fails

- **Where:** `pipeline/local_queue_worker.py:500-515`

```python
download_r2_object(bucket, object_key(prefix, "catalog.json"),
                   destination / "catalog.json", required=True)
```

`catalog.json` is required unconditionally, so a bucket that does not yet have
one raises `Could not hydrate required R2 index catalog.json: ...` and the job
fails. The season index immediately below gets this right — it derives
`required=season_exists` from the catalog contents.

**Direction:** treat a missing catalog as "bootstrap" (`required=False`) and let
`merge_incremental_indexes` skip the merge when the hydrated file is absent,
which it already handles (`local_queue_worker.py:589`).

---

### H4. Browser artifact reads are pinned to `force-cache`

- **Where:** `frontend/src/lib/api.ts:57-62`

```ts
const response = await fetch(`${source}/${path}`, {
  signal: controller.signal,
  cache: "force-cache"
});
```

`force-cache` serves any cached entry regardless of freshness. `catalog.json`,
`seasons/*.json`, and every session artifact change as sessions are ingested, so
a returning visitor keeps seeing a stale catalog indefinitely. This directly
undercuts the on-demand ingestion flow in `SessionIngestionPanel`: the job
completes, the artifacts land, and the browser still renders the old catalog.

The Worker already emits appropriate `cache-control` headers
(`worker/src/artifact-store.mjs:94-99`: 30 s for sessions, 120 s otherwise, both
with `stale-while-revalidate`).

**Direction:** drop to `cache: "default"` and let the server headers govern.

---

## Medium severity

### M1. `/live` polls forever when live mode is disabled

- **Where:** `frontend/src/components/live/LiveDataPanel.tsx:63-80`

Polling is only suppressed when the dynamic route is *missing*
(`isDynamicApiRouteMissing`). A `{ enabled: false }` payload — what the Worker
returns under the default `ENABLE_LIVE_MODE: "false"` (`wrangler.jsonc`) — is a
successful response, so `load()` returns `true` and the 4-second interval keeps
running. Each tick issues 5 requests, so every open `/live` tab costs 75 Worker
requests per minute indefinitely.

**Direction:** stop the interval once every payload satisfies `isLiveDisabled`,
leaving the existing manual "Refresh" button as the escape hatch.

---

### M2. Conditional GETs served from the static fallback return 404

- **Where:** `worker/src/artifact-store.mjs:49-63`

`get()` gates on `if (fallback?.ok)`. When the client sends `if-none-match` /
`if-modified-since` (forwarded at line 51 via `forwardedRequestHeaders`) and the
Pages origin answers `304 Not Modified`, `ok` is false, so `get()` returns
`null` and `getArtifact` responds `artifact_not_found` (404).

`head()` at lines 21-29 already accepts `ok || 304 || 416`; `get()` should
match, passing 304 and 206 through to the caller.

---

### M3. `createMemoryRepository()` throws `ReferenceError` when called without arguments

- **Where:** `worker/src/repository.mjs:279`

```js
export function createMemoryRepository(state = memoryState) {
```

`memoryState` is not defined anywhere in the repository (verified by grep across
`.mjs`/`.js`/`.ts`). All three call sites — `ingestion-callback.test.mjs:8`,
`ingestion-queue.test.mjs:9`, `session-status.test.mjs:8` — pass explicit state,
so the default is dead code that fails the moment anyone relies on it.

**Direction:** define the module-level default state, or remove the parameter
default and make `state` required.

---

### M4. `test_schedule_ingestion.py` cannot be imported

- **Where:** `backend/tests/test_schedule_ingestion.py:1-7`

The file does `from pipeline.schedule_ingestion import ...` without adding the
repository root to `sys.path`. Every sibling test does add it (for example
`test_pipeline_parity.py:8-11`, `test_local_queue_worker.py:12-13`). This is the
one file that fails locally with `ModuleNotFoundError: No module named
'pipeline'`.

`backend/pyproject.toml`'s `pythonpath = ["."]` resolves relative to `backend/`,
so pytest does not rescue it either.

**Direction:** add the same two `sys.path.insert` lines used by its siblings —
or better, fix it centrally as part of M5.

---

### M5. No CI job runs any test suite

- **Where:** `.github/workflows/` (absence)

`frontend-ci.yml` runs `npm run lint` and `npm run build` only. There is no
`pytest`/`unittest` step and no `node --test` step in any workflow, and
`worker/` has no `package.json` to hang a test script on. Grepping the whole of
`.github/`, `README.md`, and `docs/` for `pytest|unittest|node --test|npm
test|vitest` returns nothing.

Unenforced: 13 test files, roughly 1,500 lines, including
`test_pipeline_parity.py`, which exists specifically to guard the duplication
described in M8 — and which has already failed to prevent the drift in M6.

Both suites pass today, which makes this the ideal moment to lock the state in.

**Direction:** add a `backend`/`pipeline` test job and a `worker` test job to CI;
document both commands in the README.

---

### M6. Backend telemetry downsampling does not actually cap at 300 samples

- **Where:** `backend/app/analysis/telemetry_compare.py:33` vs `frontend/src/lib/static-api-core.ts:210`

```python
step = max(1, len(samples_a) // 300)      # backend  — floor
```
```ts
const step = Math.max(1, Math.ceil(samplesA.length / 300));  // frontend — ceil
```

Floor division only begins thinning at 600 samples. For a 500-sample lap the
backend returns all 500 points while the frontend returns 250. These two
implementations are meant to be parity-equivalent; this is live drift.

---

### M7. `TypeError` on pit stops with a null lap number

- **Where:** `backend/app/analysis/strategy.py:22-24`, duplicated at `pipeline/analysis/precompute.py:153-155`

```python
first_stop = min(stops, key=lambda stop: stop.get("lap_number", 999))
before = _nearest_clean_lap_time(laps, driver, int(first_stop["lap_number"]), -1)
```

The `999` default applies only when the key is *absent*, not when its value is
`None`. A present-but-null `lap_number` makes `min` compare `None` against `int`
(`TypeError`), and `int(None)` on the next line would fail regardless.

`_pit_stops` (`backend/app/ingestion/normalizer.py:379`) can emit `None` through
`_safe_int(..., default=0)` when `LapNumber` is missing.

Currently latent: 0 of 1,223 committed pit stops have a null `lap_number`.

**Direction:** coerce with `stop.get("lap_number") or 999` and skip stops with no
usable lap number.

---

### M8. The pipeline duplicates the backend analysis layer verbatim

- **Where:** `pipeline/analysis/precompute.py` vs `backend/app/analysis/`

Reimplemented in both trees, near-identically:

| Function | Backend | Pipeline |
| --- | --- | --- |
| `clean_laps` | `analysis/common.py:19` | `precompute.py:339` |
| `grouped` | `analysis/common.py:38` | `precompute.py:359` |
| `trimmed_mean` | `analysis/common.py:47` | `precompute.py:367` |
| `most_common` | `analysis/common.py:55` | `precompute.py:376` |
| `lap_statistics` | `analysis/common.py:62` | `precompute.py:383` |
| `calculate_race_pace` | `analysis/race_pace.py:7` | `precompute.py:88` |
| `calculate_strategy` | `analysis/strategy.py:5` | `precompute.py:137` |
| `calculate_ideal_laps` | `analysis/ideal_laps.py:5` | `precompute.py:185` |
| `calculate_teammate_comparison` | `analysis/teammate_comparison.py:8` | `precompute.py:213` |
| `build_position_replay` | `analysis/position_replay.py:8` | `precompute.py:257` |

`backend/app/analysis/advanced.py:622` adds a **third** copy of `clean_laps`
(`_clean_laps`).

The duplication is unforced: `pipeline/artifacts.py:12` already does
`from backend.app.ingestion.result_validation import ...`, proving the pipeline
can import backend modules directly.

**Secondary hazard — dual module identity.** `result_validation` is loaded under
two distinct module names:

- `app.ingestion.result_validation` (`backend/app/ingestion/normalizer.py:5`)
- `backend.app.ingestion.result_validation` (`pipeline/artifacts.py:12`)

Python treats these as two separate modules, so there are two distinct
`InvalidSessionResultsError` classes. Any cross-boundary `except` or `isinstance`
will silently fail to match.

**Direction:** have the pipeline import the backend analysis functions rather
than restate them, and settle on a single import root for `backend`.

---

## Low severity and cleanup

### L1. `body.txt` is a committed debug artifact

Repository root. Contents are a Cloudflare `302 Found` HTML error page. Delete.

### L2. `frontend/.env.example` is stale

Documents only `NEXT_PUBLIC_API_BASE_URL`, which no longer appears anywhere in
the code. The frontend reads `NEXT_PUBLIC_STATIC_DATA_BASE_PATH` and
`NEXT_PUBLIC_DYNAMIC_API_BASE_URL` (`frontend/src/lib/api.ts:26,32`).

### L3. `npm start` runs the dev server

`frontend/package.json`: `"start": "next dev --hostname 0.0.0.0 --port 3000"`.
With `output: "export"` there is no `next start`; the script should serve `out/`
(for example via `npx serve out`) or be removed to avoid implying otherwise.

### L4. A single null `start_date` crashes the whole scheduler

`pipeline/schedule_ingestion.py:94`:
`date.fromisoformat(str(meeting["start_date"])[:10])` raises on a null or missing
value. `normalizer._event_date` (`backend/app/ingestion/normalizer.py:588`) can
return `None`. Currently latent: 0 of 46 committed meetings are affected.

### L5. Cloudflare Access headers are stripped from the status check

`pipeline/schedule_ingestion.py:145-150` removes `CF-Access-Client-Id` and
`CF-Access-Client-Secret` from the `GET /api/session-status` request, while
`post_json` keeps them. If the Worker route is behind Cloudflare Access — which
`wrangler.jsonc` explicitly assumes whenever `REQUIRE_INGESTION_REQUEST_AUTH` is
`"false"` — the status check receives an Access login page and raises.

Also at `pipeline/schedule_ingestion.py:158-166`: `post_json` has no error
handling, so a single failed POST aborts the remaining queue.

### L6. Inconsistent pandas-optional handling in the normalizer

`backend/app/ingestion/normalizer.py:611,619` (`_timedelta_ms`, `_float_or_none`)
and `:288-289` (`pd.notna`) call pandas unguarded, while `_is_missing` at `:674`
carefully handles `pd is None`. Either the optional-pandas path is supported or
it is not.

### L7. NaN team colour becomes `"#nan"`

`backend/app/ingestion/normalizer.py:258`:
`f"#{color}" if color and not str(color).startswith("#") else color`.
`float('nan')` is truthy in Python, so a NaN `TeamColor` produces the literal
string `"#nan"`.

### L8. `_guess_session_id` cannot match name-based events

`backend/app/ingestion/fastf1_ingestor.py:1088-1093` returns
`{year}-{slug}-{code}` for string events, but real session IDs are
`{year}-{round:02d}-{code}`. The existence pre-check at line 1044 therefore never
hits for name-based events and FastF1 is reloaded every time. Harmless (a second
check follows normalization) but wasteful.

### L9. Falsy-zero guards on pace gaps

`backend/app/analysis/advanced.py:327` and `:353` use `if best else None` /
`if team_best else None`, which treat a pace of exactly 0 as missing. Should be
`is not None`.

### L10. `isEmptyState` also matches `LiveDisabledResponse`

`frontend/src/lib/static-api-core.ts:365-367` tests only for the presence of
`"reason"`, which `LiveDisabledResponse` (`:398-407`) also carries.

### L11. Standings freeze a driver's team and conflate sprint results

`frontend/src/app/standings/page.tsx:32-38`: `if (!driverMap.has(d.code))` keeps
whichever session was read first, so mid-season team changes are misattributed.
Lines 44-52 also count sprint finishes toward `podiums` and `starts` without
saying so in the UI copy.

### L12. `seriesToRows` is quadratic

`frontend/src/lib/chart-utils.ts:11-14` runs a `findIndex` per series per lap. A
`Map` keyed by `x` built once per series would make it linear. Current scale
(~20 drivers × ~70 laps) keeps this cheap, so this is style, not urgency.

### L13. Cloudflare identifiers committed in plaintext

`wrangler.jsonc:3` (`account_id`) and `:52` (`database_id`).

---

## What is working well

Recorded so it does not get lost in a future refactor:

- **Worker input validation is genuinely careful.** Bounded JSON streaming with
  a `content-length` pre-check (`worker/src/index.mjs:991`), constant-time token
  comparison with a Node fallback for the missing
  `crypto.subtle.timingSafeEqual` (`:679`), artifact-path sanitization shared
  between the Worker (`session-utils.mjs:53`) and its Python port in the
  workflow, and artifact-ownership checks bound to the job's session
  (`:900-913`).
- **Publication is checksum-verified before any status flips to `ready`**
  (`index.mjs:303-333` → `artifact-store.mjs:66-90`).
- **The job lifecycle was designed, not accreted.** The `transitionJobAndSession`
  D1 batch (`repository.mjs:144`), the partial unique index in migration 0002,
  and the queue-send compensation in `session-status.mjs:193-216` all cover real
  failure modes.
- **`_RequestPacer` (`local_queue_worker.py:423`) and the split cache
  restore/save in the workflows carry comments explaining *why*,** including the
  measurements behind the chosen defaults. That made this review substantially
  faster.
