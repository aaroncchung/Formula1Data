# Code review findings

## 1. Review metadata

| Item | Value |
| --- | --- |
| Repository | `Ntrxi/Formula1Data` |
| Branch | `fix/persist-fastf1-cache` |
| Commit reviewed | `97507c7` |
| Application code equivalent to | `fc5203e` — the only diff is `docs/code-review-findings.md` itself (`git diff --stat fc5203e..HEAD` = 1 file, +400) |
| Review date | 2026-07-25 |
| Supersedes | The previous revision of this file (findings H1–H4, M1–M8, L1–L13) |

### Scope

`worker/`, `pipeline/`, `backend/`, `frontend/`, `.github/workflows/`,
`migrations/`, root configuration and documentation.

### Environment

| Item | Value |
| --- | --- |
| OS | Windows 11 Pro 10.0.26200 |
| Node | v24.18.0 |
| npm | 11.16.0 |
| Interpreter A ("project venv") | `backend/.venv` — Python 3.12.13, with the pinned set: pandas 2.2.3, numpy 2.2.1, fastf1 3.8.3, fastapi 0.115.6, pydantic 2.10.4 |
| Interpreter B ("system") | Python 3.14.6, pandas 3.0.5 (not the pinned version; used only for cross-checking) |
| pytest | 9.1.1 (installed into both for this review; not a project dependency) |
| actionlint | **Not available on this machine — workflow linting was not performed** |

`backend/.venv` matches `backend/requirements.txt` exactly and is treated as the
authoritative environment for Python results below.

### Commands run and results

| # | Command | Working dir | Result |
| --- | --- | --- | --- |
| 1 | `node --test "worker/tests/*.test.mjs"` | repo root | **31 passed, 0 failed, 0 skipped** |
| 2 | `backend/.venv/Scripts/python.exe -m pytest backend/tests -q` | repo root | **48 passed, 2 failed** — see F-15 |
| 3 | `python -m pytest backend/tests -q` (system 3.14 / pandas 3.0.5) | repo root | 50 passed |
| 4 | `pytest.exe backend/tests -q` (console script, no cwd on `sys.path`) | repo root | 50 passed |
| 5 | `pytest.exe backend/tests/test_schedule_ingestion.py -q` | repo root | **1 collection error** — see F-14 |
| 6 | `pytest.exe backend/tests/test_backfill.py backend/tests/test_schedule_ingestion.py -q` | repo root | 6 passed — see F-14 |
| 7 | `npm ci` | `frontend/` | Success (2 install-script warnings: `sharp`, `unrs-resolver`) |
| 8 | `npm run lint` | `frontend/` | **Clean, no output** |
| 9 | `npm run build` | `frontend/` | **Success** — 290 static pages (230 session routes), TypeScript clean |
| 10 | `actionlint` | — | **Not run — binary unavailable** |

The two Python failures in the project venv (command 2) are environment-specific
and are themselves reported as F-15. They do not indicate a defect in
application code. The system-interpreter runs (commands 3–4) pass because
`GetTickCount64` resolution is incidental to which interpreter is used — the
difference is machine timing, not Python version; both were observed on this
same host and the discrepancy is explained in F-15.

### Reproductions performed

No repository files were modified. All reproductions ran from a scratch
directory against the branch's modules:

| Repro | Method | Outcome |
| --- | --- | --- |
| `createMemoryRepository()` default | ESM import, call with no args | `ReferenceError: memoryState is not defined` (F-17) |
| Fallback status handling | Stubbed `globalThis.fetch`, no R2 binding, probed 200/206/304/416/404/500 | 304 and 416 → `null` → 404; 206 passes through (F-07) |
| Telemetry downsampling | Computed backend vs frontend step for n = 300…1200 | Diverges above n=300; upstream cap makes it unreachable (F-18) |
| Empty R2 catalog bootstrap | Patched `subprocess.run` to fail all `wrangler r2 object get` | `RuntimeError: Could not hydrate required R2 index catalog.json` (F-03) |
| Scheduler after one failed candidate | Patched `get_status` / `post_json` to raise on round 1 | Rounds 2 and 3 never attempted (F-10) |
| Null `start_date` in catalog | One meeting with `start_date: null` | `ValueError: Invalid isoformat string: 'None'` (F-20) |
| Post-ingestion dashboard props | Source comparison of `SessionTabsProps` vs `loadDashboard` | 8 props omitted (F-04) |
| Cache key across rerun attempts | GitHub docs verification (`run_id`, cache immutability) | Confirmed by documentation, not executed (F-08) |
| Standings team attribution | Replayed the page's aggregation over committed artifacts | 2 within-year team changes in 2025; 0 in 2026 (F-11) |

External behaviour was verified against current GitHub and Cloudflare
documentation where it is load-bearing; those quotations are cited inline.

---

## 2. Executive summary

### Counts

| Severity | Count |
| --- | --- |
| Critical | 0 |
| High | 4 |
| Medium | 9 |
| Low | 15 |
| **Total** | **28** |

| Status | Count |
| --- | --- |
| Confirmed | 26 |
| Potential | 2 (F-08b lineage fork; F-11 currently latent for the rendered year) |
| Informational | 0 retained as standalone |

Two findings from the previous revision were **removed as unsupported**
(old L6, old L13). Five were **materially reclassified** after tracing full
execution paths. Four findings are **new**.

### Resolution status

Counts above are as-found and are not decremented as findings are fixed; each
finding's own **Status** row records whether it is still open.

| Batch | Findings | State |
| --- | --- | --- |
| 1 — test foundation and CI | F-13, F-14, F-15, F-16 | **Resolved** |
| P1 — CI and config | F-01, F-08, F-21, F-22, F-23 | **Resolved** |
| P2 — Worker HTTP | F-05, F-07, F-17 | **Resolved** |
| P3 — pipeline and backend | F-03, F-06, F-10, F-18, F-19, F-20, F-24, F-26, F-28 | **Resolved** |
| P4 — frontend UI | F-04, F-09, F-11, F-25, F-27 | **Resolved** |
| F-29 | fail-loud catalog read + download retry | **Resolved** |
| F-02 | guarded refresh with rollback | **Resolved** |
| F-12 | analysis-layer deduplication | **Resolved** |
| F-30, F-31 | found while fixing F-12 | **Resolved** |
| F-32 | complete backup before a refresh overwrites | **Resolved** |

**All 32 findings are resolved.** Twenty-nine came from the review itself; F-29
was introduced by the review's own F-03 fix, F-30/F-31 were found while
resolving F-12, and F-32 came from review feedback on PR #6 against the F-02
fix — the guard could skip or half-fill its backup and still overwrite.

The Python suite is 79/79 and the Worker suite 55/55, both run by
`.github/workflows/tests.yml` on every pull request and push to `main`. Later
batches are therefore regression-checked by CI rather than by hand.

### Highest priority

1. **F-01** — Bulk-dispatched ingestion runs are cancelled by the shared
   concurrency group, silently losing jobs. A one-line `queue: max` fix now
   exists in GitHub's syntax.
2. **F-02** — A failed forced refresh overwrites live R2 session bodies in
   place, leaving a published session pointing at a mix of generations that
   nothing on the read path validates.
3. **F-03** — The first ingestion into a fresh R2 bucket always fails.
4. **F-04** — Successful on-demand ingestion renders a materially degraded
   dashboard versus the statically built page, defeating the feature's purpose.

### Substantive changes from the previous revision

| Old ID | Change |
| --- | --- |
| H1 | Retained High. **Corrected:** the stale-job message does not mention FastF1. **Added:** GitHub's `concurrency.queue: max` changes the recommended fix. |
| H2 | **Downgraded High → Medium** (F-06). The claim that this path is reached for "all 33 committed sessions" was wrong: `resolveSessionStatus` short-circuits before a job is ever queued, and `force` routes to the fresh path. |
| H3 | Retained High (F-03), now with a reproduction. |
| H4 | **Downgraded High → Medium** (F-05); "indefinitely" removed. **Added:** fixing it in isolation exposes F-07. |
| M2 | **Corrected** (F-07): 206 is fine; 304 **and 416** are the broken cases. |
| M4 | **Downgraded Medium → Low** (F-14). The file is *not* dead — it passes in full-suite runs. The real defect is a cross-file `sys.path` ordering dependency. |
| M6 | **Downgraded Medium → Low** (F-18). The divergence is unreachable: telemetry is capped at 300 samples/lap upstream, so both implementations agree on every reachable input. The previous claim of "live drift" was wrong. |
| M7 | **Downgraded Medium → Low** (F-19). The normalizer cannot emit `None`; `_safe_int(..., default=0)` returns `0`. |
| M8 | **Retained Medium** (F-12), reworded: "verbatim" removed, return-type and import-root obstacles documented, dual-module identity marked as a hazard with no demonstrated failing boundary. |
| L5 | **Upgraded Low → Medium** (F-10), but **the Cloudflare Access premise was removed as unsupported** — the docs state status checks are public. The confirmed defect is fail-fast abort. |
| L11 | **Upgraded Low → Medium** (F-11), split into team attribution vs. UI semantics, with data evidence. |
| L6 | **Removed — unsupported.** |
| L13 | **Removed — unsupported.** |
| — | **New:** F-02, F-04, F-08, F-15, F-16. |

---

## 3. Findings

### F-01 — Shared concurrency group cancels pending ingestion runs

| | |
| --- | --- |
| **Category** | CI/CD orchestration, job loss |
| **Severity** | High |
| **Confidence** | High |
| **Status** | **Resolved (batch P1)** |

**Resolution** Added `queue: max` to the `concurrency` block in `process-ingestion-job.yml`, alongside the existing `cancel-in-progress: false` (the two are compatible; `queue: max` with `cancel-in-progress: true` is a validation error). A comment records the documented 100-pending ceiling and that a full backfill can still exceed it. Separately, `dispatchGitHubWorkflow` in `worker/src/index.mjs` now reverts the job to `queued` with `started_at` cleared whenever the dispatch is unconfirmed -- both a thrown fetch and a retryable status -- so D1 distinguishes "never started" from "started and hung" instead of waiting two hours for the stale reconciler to report a timeout that never happened. `schedule-ingestion.yml` was deliberately left alone: its group serialises an hourly cron whose evicted ticks are re-queued an hour later, so the eviction is cheap there.

**Locations**

- `.github/workflows/process-ingestion-job.yml:21-23`
- `.github/workflows/schedule-ingestion.yml:16-18`
- `pipeline/schedule_ingestion.py:88-104`
- `wrangler.jsonc:55-62` (queue consumer batching)
- `worker/src/index.mjs:463-480` (job marked `running` before dispatch)
- `worker/src/index.mjs:178-188` (only cleanup mechanism)

**Reachability**

`schedule-ingestion.yml` runs hourly (`cron: "37 * * * *"`) and
`pipeline.schedule_ingestion` POSTs one request per candidate session
(`--sessions FP1 FP2 FP3 SQ S Q R`). The Worker queue consumer is configured
`max_batch_size: 10`, `max_concurrency: 1` (`wrangler.jsonc:57,62`), so a single
consumer invocation can issue up to ten `repository_dispatch` calls in immediate
succession. Every resulting workflow run shares `concurrency.group: ingestion`.

**Observable impact**

GitHub's documented behaviour, verified against current syntax reference:

> "any existing `pending` job or workflow run in the same concurrency group will
> be canceled and the new queued job or workflow will take its place."

With one run executing and one pending, each additional dispatch evicts the
previously pending run. Most dispatched sessions are therefore never ingested.

Because `dispatchQueueMessage` sets the job to `running` **before** dispatching
(`index.mjs:463-468`, dispatch at `:477-480`) and nothing reverts it when the
workflow is cancelled, those jobs sit in D1 as `running` until the 30-minute
cron reconciler fails them after `STALE_JOB_TIMEOUT_MINUTES` (120). That is the
only cleanup mechanism.

**Code evidence**

```yaml
# .github/workflows/process-ingestion-job.yml:21-23
concurrency:
  group: ingestion
  cancel-in-progress: false
```

```js
// worker/src/index.mjs:184-187 — the resulting failure text
`Ingestion did not complete within ${timeoutMinutes} minutes`
```

**Correction to the previous revision:** that message contains no reference to
FastF1. It is generic. The misleading aspect is that it describes a *timeout*
when the actual event was a *cancellation that never started* — the job's
`started_at` is set, so the run looks like it began and hung.

**Recommended direction**

GitHub now supports a `queue` property on `concurrency`, verified against the
current workflow-syntax reference:

> "`max`: Up to 100 jobs or workflow runs can be `pending` in the concurrency
> group."
>
> "The combination of `queue: max` and `cancel-in-progress: true` is not allowed
> and will result in a workflow validation error."

Since this workflow already sets `cancel-in-progress: false`, adding
`queue: max` is compatible and is the minimal fix. Note the 100-pending ceiling:
a full backfill (7 codes × 24 meetings = 168 candidates) can still exceed it, so
for bulk work prefer either a per-session group
(`group: ingestion-${{ github.event.client_payload.message.session_id }}`,
which also unlocks parallelism) or a single draining runner. Independently,
consider reverting the job to `queued` when dispatch cannot be confirmed, so the
D1 state distinguishes "never started" from "started and hung".

**Effort** S for `queue: max`; M for per-session groups or a draining runner.

**Suggested regression tests**

- A Worker unit test asserting a job is not left `running` when dispatch fails.
- A workflow-level smoke test dispatching three sessions and asserting three
  completions (would have caught this).

---

### F-02 — Failed forced refresh corrupts a published R2 session

| | |
| --- | --- |
| **Category** | Data integrity |
| **Severity** | High |
| **Confidence** | High |
| **Status** | **Resolved** |

**Resolution** A refresh now takes a local backup of the live generation before overwriting any body, and restores it if a body upload exhausts its retries. The guard lives inside `sync_artifacts_to_r2`, so the fresh-ingestion and reuse paths both get it unchanged; an existing generation is detected by probing for the remote manifest, which is reliable now that `download_r2_object` retries (F-29). A first publication pays only the probe. The upload error is held rather than propagated so the rollback runs after the executor shuts down -- restoring while a straggler upload was still in flight could re-corrupt the key it had just restored. A failed restore raises naming the session and stating it may be inconsistent.

Immutable generation-prefixed keys were considered and rejected: the frontend addresses artifacts by convention (`static-api-core.ts` builds `sessions/<id>/summary.json` from hardcoded filenames, and telemetry paths are relative to the session directory), so that scheme would force every read through the manifest. The key layout is unchanged and neither the frontend nor the Worker was touched. Cost: a refresh roughly doubles its R2 operations; a first publication pays 3 extra GETs.

**Residual, accepted:** the guard covers body uploads only. If every body lands and the manifest PUT then exhausts its retries, the session is a complete new generation described by the old manifest. `verify_remote_manifest` fails, the job is marked failed, and a re-run repairs it -- stale metadata rather than mixed data. Pulling the manifest inside the guarded region would make a rollback re-PUT a marker key, contradicting the existing invariant that markers never follow a failed body upload.

**Locations**

- `pipeline/local_queue_worker.py:306-364` (`sync_artifacts_to_r2`)
- `pipeline/local_queue_worker.py:347-360` (failure handling)
- `worker/src/index.mjs:153-176` (`getArtifact` — read path)
- `worker/src/artifact-store.mjs:66-90` (`verify` — the only checksum check)

**Reachability**

Requires two conditions:

1. A **forced** re-ingestion of a session already published to R2. Reachable via
   the UI retry button (`SessionIngestionPanel.tsx:268` passes `force` when the
   status is `failed`), `pipeline.schedule_ingestion --force`, and the workflow
   `force` input.
2. An upload failure that survives `R2_UPLOAD_ATTEMPTS` retries. The module's own
   pacer and throttle-backoff logic (`:423-497`) exists precisely because R2 rate
   limiting is expected under a ~1,000-PUT session.

On *first* publication there are no prior bodies, so a partial failure merely
leaves an unreferenced set with no manifest — readers correctly see "not ready".
Corruption is specific to refresh.

**Observable impact**

Bodies are uploaded to the **same keys** as the live generation, concurrently,
before any commit marker:

```python
# pipeline/local_queue_worker.py:325-328
bodies  = [path for path in session_files if path != manifest and path.is_file()]
markers = [manifest] if manifest.is_file() else []
if include_indexes:
    markers.extend([output_dir / "seasons" / f"{year}.json", output_dir / "catalog.json"])
```

If a body upload fails part-way, the old `manifest.json` remains published while
the underlying object set is a mixture of old and new generations. The module
documents this honestly:

```python
# pipeline/local_queue_worker.py:351-357
# Bodies are overwritten in place over the live session, so a
# failure part-way leaves the published manifest pointing at a
# mix of old and new files. Cancelling drops uploads that have
# not started yet; ones already running still finish, because
# leaving the executor shuts it down with wait=True. This only
# narrows the window. Publishing to immutable per-generation
# keys is the actual fix and is not done here.
```

The decisive aggravating factor is that **nothing detects the inconsistency**.
`artifacts.verify()` is called exactly once in the entire Worker
(`index.mjs:306`), against the **manifest only**, with `r2Only: true`, at
job-completion time. Section artifacts listed in the manifest are never
checksum-verified — not at write time, not at read time. `getArtifact`
(`index.mjs:153-176`) performs a path allowlist check and streams the object.
So a corrupted session serves silently corrupted analysis data indefinitely,
while the job itself is marked `failed` and gives no indication that published
data was damaged.

**Recommended direction**

Publish to immutable, generation-prefixed keys and flip the manifest as the
single atomic commit marker — the fix the code comment already identifies. A
cheaper interim mitigation: on failure, re-upload the previous generation's
bodies, or refuse to start a forced refresh unless a full rollback copy exists.
Independently, consider verifying a sample of section checksums during the
success callback rather than the manifest alone.

**Effort** L (key-scheme change touches `sync_artifacts_to_r2`,
`build_success_payload`, manifest paths, and the Worker's ownership validation).

**Suggested regression tests**

- Patch `upload_r2_object` to fail on the Nth body; assert the previously
  published manifest and its referenced bodies remain mutually consistent.
- A Worker test asserting a section whose bytes do not match its recorded
  checksum is detectable through whatever verification path is added.

---

### F-03 — First ingestion into an empty R2 bucket always fails

| | |
| --- | --- |
| **Category** | Bootstrap / deployment |
| **Severity** | High |
| **Confidence** | High |
| **Status** | **Resolved (batch P3)** |

**Resolution** `hydrate_r2_indexes` now downloads `catalog.json` with `required=False` and only derives `season_exists` when the catalog was actually hydrated; the season index keeps its conditional `required`. Empty-bucket bootstrap succeeds and `merge_incremental_indexes` no-ops through its existing `is_file()` guards. **This fix introduced F-29 — read that before deploying.** `test_r2_hydration_requires_the_current_catalog` was replaced rather than weakened: it asserted the defect itself. Its remaining value is now `test_r2_hydration_still_requires_a_season_index_the_catalog_claims`.

**Locations**

- `pipeline/local_queue_worker.py:500-515` (`hydrate_r2_indexes`)
- `pipeline/local_queue_worker.py:586-601` (`merge_incremental_indexes`)

**Reachability**

Any `--artifact-destination r2` ingestion into a bucket that does not yet
contain `catalog.json` — i.e. every green-field deployment following
`docs/production-ingestion-setup.md` that has not manually pre-seeded the
bucket. (Section 6 of that document does show a manual `catalog.json` upload,
which is why this has not blocked the existing deployment; it makes the manual
step mandatory rather than optional, undocumented as such.)

**Observable impact**

```python
# pipeline/local_queue_worker.py:502-507
download_r2_object(
    bucket,
    object_key(prefix, "catalog.json"),
    destination / "catalog.json",
    required=True,          # <-- unconditional
)
```

Reproduction, with `subprocess.run` patched to fail every `wrangler r2 object
get`:

```
RuntimeError: Could not hydrate required R2 index catalog.json:
The specified key does not exist.
```

The season index immediately below gets this right — it derives
`required=season_exists` from the catalog contents (`:509-515`). And the
downstream consumer already tolerates absence; the same reproduction confirms
`merge_incremental_indexes` no-ops cleanly when the hydrated directory is empty
(guarded by `is_file()` at `:589` and `:597`).

**Recommended direction**

Treat a missing catalog as bootstrap: `required=False`, then let the existing
`is_file()` guards skip the merge. The freshly built catalog is then published
as-is, which is the correct outcome for an empty bucket.

**Effort** S (one argument, plus a test).

**Suggested regression test**

The reproduction above, asserting `hydrate_r2_indexes` succeeds and the
published catalog contains exactly the newly ingested session.

---

### F-04 — On-demand ingestion renders a degraded dashboard

| | |
| --- | --- |
| **Category** | Feature completeness / correctness |
| **Severity** | High |
| **Confidence** | High |
| **Status** | Confirmed |

**Locations**

- `frontend/src/components/session/SessionIngestionPanel.tsx:68-158` (`loadDashboard`)
- `frontend/src/components/session/SessionTabs.tsx:61-82` (`SessionTabsProps`)
- `frontend/src/components/session/SessionTabs.tsx:264-273` (`TelemetryView`)
- `frontend/src/app/seasons/[year]/[round]/[session]/page.tsx:40-61,125-150` (the static path, for contrast)

**Reachability**

This is the path a user takes after clicking "Queue ingestion" for a session
absent from the static build and waiting for it to complete — the entire purpose
of the on-demand ingestion feature. It requires hybrid mode, which `README.md:413`
documents: *"configure `/api/*` and `/data/*` to reach the Worker, or set
`NEXT_PUBLIC_DYNAMIC_API_BASE_URL` and `NEXT_PUBLIC_STATIC_DATA_BASE_PATH` to
the Worker origin."* In the committed static-only defaults
(`frontend/wrangler.jsonc:6-7`) the panel short-circuits to "static-only" mode
and never reaches `loadDashboard`.

**Observable impact**

The static page fetches 20 artifacts and passes 20 props. `loadDashboard`
fetches 13 and passes 13. Eight props are missing:

| Prop | Fetched by `loadDashboard`? | Passed to `SessionTabs`? |
| --- | --- | --- |
| `telemetryIndex` | **Yes** (`:96`) | **No** |
| `idealLaps` | No | No |
| `teammateComparison` | No | No |
| `strategy` | No | No |
| `trackDominance` | No | No |
| `cornerAnalysis` | No | No |
| `carPerformance` | No | No |
| `pacePrediction` | No | No |

All eight are declared optional in `SessionTabsProps` (`SessionTabs.tsx:74-82`),
so this is not a type error — which is why `npm run lint` and `npm run build`
both pass cleanly. Consequences per tab:

- **Telemetry** — `TelemetryView` passes `availableLaps={telemetryIndex?.laps || []}`
  (`SessionTabs.tsx:273`). With the index omitted, both driver selectors and both
  lap selectors render empty. The initial comparison chart still displays, so the
  tab looks functional while being frozen on one pair of laps. This is the
  sharpest symptom: the data was fetched and then discarded one line before use.
- **Performance** — all four advanced sections are gated on
  `props.X?.length` (`PerformanceAnalysis.tsx:42,48,54,60`) and are therefore
  hidden; the two remaining panels render their null empty-states.
- **Strategy** — `compound_usage`, `undercut_overcut` and `pit_loss_estimate_ms`
  are all absent (`StrategyAnalysis.tsx:7-9,22`); the view degrades to raw pit
  stops.

The underlying artifacts exist — `precompute_session_analysis`
(`pipeline/analysis/precompute.py:31-53`) generates all of them and they are
uploaded with the session. The client simply never requests them.

**Recommended direction**

Extract the artifact fan-out shared by the server page and `loadDashboard` into
one function returning a complete `SessionTabsProps`, so the two paths cannot
diverge again. As a minimum, add the seven missing fetches and pass
`telemetryIndex` through. Consider making the eight props required and supplying
explicit `null`s, so omission becomes a compile error.

**Effort** S–M.

**Suggested regression tests**

- A unit test asserting the key set produced by `loadDashboard` equals the key
  set passed by the server component.
- A component test asserting the telemetry driver selector is non-empty when a
  telemetry index is available.

---

### F-05 — Static artifact reads are pinned to `force-cache`

| | |
| --- | --- |
| **Category** | Caching / data freshness |
| **Severity** | Medium |
| **Confidence** | High |
| **Status** | **Resolved (batch P2)** |

**Resolution** `frontend/src/lib/api.ts` now uses `cache: "default"`, so the Worker's existing `cache-control` headers govern. Landed **after** F-07 -- fixing it first would have restored conditional revalidation while the Worker still turned a fallback 304 into a 404.

**Locations** `frontend/src/lib/api.ts:57-62`; contrast
`worker/src/artifact-store.mjs:94-99`.

**Reachability** Every browser artifact read on a repeat visit.

**Observable impact**

```ts
const response = await fetch(`${source}/${path}`, {
  signal: controller.signal,
  cache: "force-cache"
});
```

Per the Fetch specification, `force-cache` returns a matching cached entry
**fresh or stale**, and only issues a network request when there is no match. It
does not revalidate. `catalog.json`, `seasons/*.json` and session artifacts all
change as sessions are ingested, so a user who has previously loaded a page can
continue to see a superseded catalog. Meanwhile the Worker's carefully chosen
headers (30 s for `sessions/`, 120 s otherwise, both with
`stale-while-revalidate`) have no effect on these requests.

**Corrected from the previous revision:** this is not permanent. Normal browser
cache eviction, a hard refresh, a private window, or storage pressure will all
clear the entry. The accurate characterisation is that an ordinary returning
visitor has no reliable way to obtain fresh data through normal navigation, and
the staleness window is bounded only by the browser's eviction policy rather
than by any header the project controls.

**Important interaction:** fixing this in isolation makes **F-07** acutely
reachable. Once conditional revalidation resumes, every `if-none-match`
revalidation of an artifact served from the Pages fallback returns 304 to the
Worker, which converts it to a 404. Fix F-07 first, or fix both together.

**Recommended direction** Use `cache: "default"` and let the Worker's
`cache-control` headers govern.

**Effort** S (one line) — but sequence it after F-07.

**Suggested regression test** Assert that a second read after an artifact
changes on the origin returns the new payload.

---

### F-06 — Reuse path publishes a session without updating the R2 indexes

| | |
| --- | --- |
| **Category** | Data consistency |
| **Severity** | Medium (**downgraded from High**) |
| **Confidence** | High |
| **Status** | **Resolved (batch P3)** |

**Resolution** The reuse branch now calls a new `publish_indexes_to_r2()`, which hydrates R2's indexes into a temp directory, merges the local `catalog.json` and `seasons/<year>.json` in, and uploads season-then-catalog. A temp directory is used because `output_dir` is the committed artifact tree. `sync_artifacts_to_r2` and its `include_indexes` contract are untouched, so F-02 is not pre-empted. Note the merge carries the whole committed local catalog into R2's, not only the reused session -- consistent with the Worker's Pages fallback, but broader than "add one session".

**Locations**

- `pipeline/local_queue_worker.py:101-104` (branch condition)
- `pipeline/local_queue_worker.py:160-168` (`include_indexes=False`)
- `pipeline/local_queue_worker.py:113-158` (the correct branch, for contrast)
- `worker/src/session-status.mjs:122-138` (upstream short-circuit)

**Reachability — corrected**

The previous revision claimed this branch is taken for "all 33 committed
sessions". Tracing the full path shows that is wrong:

1. `GET /api/session-status` → `resolveSessionStatus` calls
   `artifacts.head(sessionManifestPath(...))` (`session-status.mjs:16-20`), which
   checks R2 and then falls back to `STATIC_DATA_BASE_URL`. For a committed
   session with a healthy Pages origin the manifest is found → status `ready`.
2. `enqueueIngestionJob` then returns early:
   `if (current.status === "ready" && !force) return { action: "ready", job: null }`
   (`session-status.mjs:124-130`). **No job is queued at all**, so
   `process_message` is never invoked.
3. If `force` *is* set, it propagates into the queue message
   (`session-status.mjs:183` → `session-utils.mjs:97`) and
   `should_force = force or bool(message.get("force"))`
   (`local_queue_worker.py:100`) selects the **fresh** branch, not the reuse
   branch.

So the reuse branch requires all of: a job was queued (manifest missing from
**both** R2 and the Pages fallback), `force` is false, and the runner's checkout
*does* contain `frontend/public/data/sessions/<id>/manifest.json`.

That combination is reachable, principally because Pages deploys are manual
(`cloudflare-pages.yml` is `workflow_dispatch` only). Artifacts committed to
`main` by `generate-artifacts.yml` exist in the runner's checkout but not on the
deployed Pages origin until someone redeploys. A `STATIC_DATA_BASE_URL` outage or
misconfiguration produces the same window.

**Observable impact**

In that window the session's own files are uploaded to R2 but `catalog.json` and
`seasons/<year>.json` are not, and `merge_incremental_indexes` is never called
on this branch. The job reports `succeeded` while the session remains absent from
the catalog any hybrid-mode client reads.

The reuse behaviour itself is intentional and documented (`README.md:212`); the
index omission is the defect. The asymmetry with the fresh branch — which does
call `merge_incremental_indexes` and defaults `include_indexes=True` — is the
clearest evidence it is unintended.

**Recommended direction** Run the index merge and marker upload on both branches.

**Effort** S.

**Suggested regression test** Assert the reuse branch uploads `catalog.json` and
`seasons/<year>.json`. Note the existing suite only tests
`session_artifacts_exist` for the *False* case
(`test_local_queue_worker.py:72-73`), which is why this survived.

---

### F-07 — Fallback `304` and `416` responses become `404`

| | |
| --- | --- |
| **Category** | HTTP correctness |
| **Severity** | Medium |
| **Confidence** | High |
| **Status** | **Resolved (batch P2)** |

**Resolution** `artifact-store.mjs` gained a shared `isAcceptableFallback()` (`ok || 304 || 416`) used by both `head()` and `get()`, removing the asymmetry that caused this. `get()` forwards the upstream status and headers, passing a `null` body for null-body statuses so the `Response` constructor does not throw on a 304. 206 was already correct and is untouched. Verified with the review's original probe: 304 and 416 now return `Response 304` / `Response 416` where they previously returned `null`, while 404 and 500 still return `null`. 13 regression tests assert the full probe table across both methods.

**Locations** `worker/src/artifact-store.mjs:49-63` (`get`); contrast
`:21-29` (`head`).

**Reachability** Hybrid mode, where `/data/*` is routed to the Worker
(`README.md:413`), for any artifact not in R2 — which is every committed session,
since only newly ingested sessions are written to R2. Currently masked by F-05,
because `force-cache` suppresses conditional requests; unmasked the moment F-05
is fixed.

**Observable impact — corrected**

Reproduction with no R2 binding and a stubbed fallback origin:

```
fallback 200 (OK               ) -> get(): Response 200
fallback 206 (Partial Content  ) -> get(): Response 206
fallback 304 (Not Modified     ) -> get(): null -> caller emits 404 artifact_not_found
fallback 416 (Range Not Satisf.) -> get(): null -> caller emits 404 artifact_not_found
fallback 404 (Not Found        ) -> get(): null -> caller emits 404 artifact_not_found
fallback 500 (Server Error     ) -> get(): null -> caller emits 404 artifact_not_found
```

The previous revision named only 304. **206 is not affected** — it satisfies
`Response.ok`. **416 is affected** and was missed. The cause is the single gate:

```js
// worker/src/artifact-store.mjs:62
if (fallback?.ok) { ... }
return null;
```

`head()` already handles this correctly — `fallback.ok || fallback.status === 304
|| fallback.status === 416` (`:22`) — so the two methods disagree about what
constitutes a successful fallback. `resolveSessionStatus` uses `head()` and is
therefore unaffected.

**Recommended direction** Mirror the `head()` acceptance set in `get()` and pass
304/416 through to the caller with their headers.

**Effort** S.

**Suggested regression test** The probe table above, asserted per status code.

---

### F-08 — FastF1 cache: snapshot churn, and reruns that cannot improve the cache

| | |
| --- | --- |
| **Category** | CI/CD efficiency and correctness |
| **Severity** | Medium |
| **Confidence** | High (a, b) / Low (c) |
| **Status** | **Resolved (batch P1)** |

**Resolution** `github.run_attempt` was added to the restore and save keys in both workflows, so a re-run no longer hits its own immutable entry from attempt 1 and can write an improved cache. Saves are now gated on a path-and-size fingerprint taken before ingestion and recompared afterwards, replacing the `hashFiles(...) != ''` guard that restored files alone satisfied -- an unchanged cache is no longer re-uploaded. (c), the warm/ingestion lineage fork, was left as-is: it is Potential-confidence and the shared lineage is currently intentional.

**Locations**

- `.github/workflows/process-ingestion-job.yml:66-73` (restore), `:207-215` (save)
- `.github/workflows/warm-fastf1-cache.yml:59-66` (restore), `:103-109` (save)

Both workflows use the identical key
`${{ runner.os }}-fastf1-${{ hashFiles('backend/requirements.txt') }}-${{ github.run_id }}`
with the same two restore-key prefixes.

**(a) Every run uploads a full new snapshot — Confirmed**

The save condition is `if: always() && hashFiles('backend/data/cache/fastf1/**') != ''`.
Restored files satisfy that predicate, so a run that downloaded nothing new still
saves. Because the key embeds `github.run_id`, every run writes a *new* immutable
entry containing the entire restored cache plus any delta.

Verified against GitHub's caching reference: the limit is *"10 GB per
repository"*, entries *"that have not been accessed in over 7 days"* are removed,
and when storage is exceeded *"the cache eviction policy will create space by
deleting the caches in order of last access date, from oldest to most recent."*
With hourly scheduling and multi-hundred-megabyte FastF1 caches, near-duplicate
snapshots accumulate quickly and evict each other.

**(b) Re-runs are pinned to the first attempt's partial cache — Confirmed**

Verified against GitHub's context reference:

> `github.run_id` — *"This number does not change if you re-run the workflow run."*
> `github.run_attempt` — *"begins at 1 ... and increments with each re-run."*

And the caching reference: *"You cannot change the contents of an existing cache.
Instead, you can create a new cache with a new key."*

Therefore, on attempt 1 the restore primary key never matches (nothing saved
under it yet) and the prefix restore-keys select the newest available snapshot;
the save then writes that key. On attempt 2 the primary key now matches
**exactly**, so the restore returns attempt 1's possibly-partial cache in
preference to any older, more complete snapshot — and the subsequent save cannot
replace the immutable entry. `continue-on-error: true` conceals that failure.

This directly undercuts the stated purpose of commit `fc5203e` ("Persist the
FastF1 cache even when a run fails"): a re-run, the most natural response to a
failure, is exactly the case that cannot improve the cache.

**(c) Warm/ingestion lineage fork — Potential**

The two workflows use different concurrency groups (`fastf1-cache` vs
`ingestion`) but the same key namespace, so they can run concurrently, both
restore snapshot A, add different sessions, and save A+B and A+C under separate
run ids. A later prefix restore selects one snapshot rather than their union, so
one lineage's work is dropped. This follows from the key design but **was not
demonstrated against real workflow runs** and is reported as potential.

**Not asserted:** whether `if: always()` reliably completes a large cache upload
when the 90-minute job timeout fires or the runner is terminated. `always()` does
schedule the step on cancellation, but the grace window is bounded and a runner
loss executes nothing. This was evaluated and is recorded as a caveat rather than
a separate finding.

**Recommended direction**

Include `github.run_attempt` in the save key so re-runs can write, and gate the
save on the cache having actually changed (for example, record a file count or
digest after restore and compare before saving). Consider separate key namespaces
for the warm and ingestion workflows, or a single scheduled warm job that owns
the lineage.

**Effort** S–M.

**Suggested regression test** Not unit-testable; verify by inspecting two
consecutive runs and one re-run in the Actions cache list.

---

### F-09 — `/live` polls indefinitely when live mode is disabled

| | |
| --- | --- |
| **Category** | Resource consumption |
| **Severity** | Medium |
| **Confidence** | High |
| **Status** | Confirmed |

**Locations** `frontend/src/components/live/LiveDataPanel.tsx:34-80`;
`worker/src/index.mjs:369-372`; `wrangler.jsonc:8` (`ENABLE_LIVE_MODE: "false"`).

**Reachability** Any visitor on `/live` in hybrid mode — the default Worker
configuration ships with live mode disabled.

**Observable impact** Polling is suppressed only when the dynamic route is
*missing* (`isDynamicApiRouteMissing`, `:47-54`). A `{ enabled: false }` body is
a 200 response, so `load()` returns `true` and the interval established at
`:70-74` keeps running. Each tick issues five requests
(`liveCurrentSession`, `liveTiming`, `liveRaceControl`, `livePositions`,
`liveWeather`) every 4 s — 75 Worker requests per minute per open tab, for a
panel that renders a static "Live mode is disabled" message.

**Recommended direction** Stop the interval once every payload satisfies
`isLiveDisabled`; the existing manual "Refresh" button already covers recovery.

**Effort** S.

**Suggested regression test** Assert no interval is registered when all five
payloads report `enabled: false`.

---

### F-10 — One failed candidate aborts the entire scheduler run

| | |
| --- | --- |
| **Category** | Reliability |
| **Severity** | Medium (**upgraded from Low**) |
| **Confidence** | High |
| **Status** | **Resolved (batch P3)** |

**Resolution** Each candidate in `pipeline/schedule_ingestion.py` is now wrapped individually; failures are logged to stderr and counted, the summary reports them, and `main` exits non-zero when any failed. A regression test asserts round 3 is still queued when round 1's status check and round 2's POST both raise.

**Locations** `pipeline/schedule_ingestion.py:106-124` (the loop),
`:145-166` (`get_status`, `post_json`).

**Reachability** Every hourly `schedule-ingestion.yml` run. Any transient error
on any candidate — one 5xx, one timeout, one malformed response — aborts the run.

**Observable impact** Reproduction with three candidates where round 1's status
check raises:

```
outcome            : RuntimeError: Ingestion API returned a non-JSON response ...
status checks tried: rounds [1]
sessions queued    : rounds []
-> rounds never reached: [2, 3]
```

And with a failing POST instead:

```
outcome            : RuntimeError: HTTP Error 500
status checks tried: rounds [1]
sessions queued    : rounds []
```

Neither `get_status` nor `post_json` catches anything, and the loop has no
per-candidate error handling, so the first failure propagates out of `main`.
Candidates are ordered by meeting, so a persistent problem with an early round
permanently starves every later round.

**Premise removed:** the previous revision attributed this to Cloudflare Access
returning an HTML login page, because `get_status` strips
`CF-Access-Client-Id`/`CF-Access-Client-Secret` (`:145-150`) while `post_json`
retains them. That premise is **unsupported**:
`docs/production-ingestion-setup.md:178` scopes the Access application to
`api.example.com/api/ingestion/*`, and `:206` states *"Historical reads and
session status checks remain public."* The header stripping is therefore
deliberate and correct for the documented topology. It would only bite a
deployment that placed Access across the whole hostname, contrary to the guide.

**Recommended direction** Wrap each candidate in `try/except`, log and count
failures, continue, and exit non-zero at the end if any failed.

**Effort** S.

**Suggested regression test** The reproduction above, asserting rounds 2 and 3
are still queued when round 1 fails.

---

### F-11 — Season standings freeze a driver's team at first appearance

| | |
| --- | --- |
| **Category** | Domain correctness |
| **Severity** | Medium (**upgraded from Low**) |
| **Confidence** | High |
| **Status** | Confirmed defect; currently latent for the rendered year |

**Locations** `frontend/src/app/standings/page.tsx:30-38` (driver map),
`:54-63` (aggregation), `:97-110` (`ConstructorStandings`).

**Reachability**

```ts
for (const d of resp.data) {
  if (!driverMap.has(d.code)) { driverMap.set(d.code, d); }   // first-seen wins
}
```

`pointSessions` derives from the catalog, which `write_catalog`
(`pipeline/artifacts.py:117`) sorts by `(year, round, type)`, so "first" is the
earliest round. A driver's entire season — points, wins, podiums — is attributed
to whichever team they drove for in their earliest committed race, and
`ConstructorStandings` groups by that frozen `team.team_id`.

Replaying the page's aggregation over the committed artifacts:

| Year | Point sessions | Drivers with a within-year team change |
| --- | --- | --- |
| 2025 | 24 | **2** — `TSU` Racing Bulls → Red Bull Racing (round 3); `LAW` Red Bull Racing → Racing Bulls (round 3) |
| 2026 | 9 | 0 |

The page renders only `primarySession.year`, which currently resolves to **2026**
(`2026-09-r`), where no within-year change exists — so today's output is correct.
The 2025 data in this same repository would be misreported: TSU's full season
credited to Racing Bulls and LAW's to Red Bull Racing, each the opposite of where
they scored most of their points. There is no year selector, so the wrong year is
not currently selectable — but a mid-season swap is an ordinary, recurring event
requiring no unusual input, and the failure is silent.

**Separate, lower-severity issue in the same component:** `pointSessions` includes
`S` (sprint) sessions (`:20-22`), whose finishes are counted into columns labelled
"Wins", "Podiums" and "Starts" (`:47-50`) without qualification. The committed
catalog contains 33 point sessions, **all of type `R`**, so this is latent today.

**Recommended direction** Key the aggregation by `(driver, session)` and attribute
each session's points to the team recorded *for that session*; derive constructor
totals from those per-session pairs. Separately, either exclude sprints or label
the columns to include them.

**Effort** M.

**Suggested regression test** A fixture with a driver moving teams at round 3;
assert points split across both constructors in the correct proportion.

---

### F-12 — Pipeline duplicates the backend analysis layer

| | |
| --- | --- |
| **Category** | Maintainability |
| **Severity** | Medium |
| **Confidence** | High |
| **Status** | **Resolved** |

**Resolution** There is now one analysis layer. `pipeline/analysis/precompute.py` drops from 468 to 118 lines and implements nothing -- it names the artifacts and routes each to the shared function in `backend/app/analysis/`, keeping only its two genuinely pipeline-only pieces. The third lap-filter copy, `advanced._clean_laps`, is deleted in favour of `common.clean_laps`. Module and function names are preserved.

The Pydantic/dict split was resolved at the route boundary as recommended: shared functions return dicts, and `analysis.py` and `telemetry.py` wrap them (`RacePaceResult(**...)`, `[PositionReplayFrame(**f) ...]`). `response_model` declarations are unchanged and pydantic is verified absent from the pipeline import graph.

**The import root was deliberately not standardised.** Both directions break an invariant: `backend.app.*` breaks the container (`WORKDIR /app`, no `backend` parent), and `app.*` would require a `sys.path` mutation as an import side effect in `pipeline/__init__.py`. The enabling property turned out to be root-agnosticism rather than a single root name -- sibling imports inside the shared package are now relative and no shared module reaches into `app.models`. Both entry points verified: `app.main` imports with only `backend/` on the path and no `backend.*` leakage; `python -m pipeline` still works from the repo root. **The dual-module identity hazard is untouched and still latent**, and this refactor was audited not to spring it: no custom exception class crosses the boundary.

`test_pipeline_parity.py` was strengthened, not retired -- it now asserts all ten pairs resolve to one source file, that `advanced` uses the shared filter, and that no shared module imports outside its package. Identity comparison is unavailable because the package is genuinely loaded twice under two module names.

Behaviour was checked rather than assumed: generating the sample artifacts from pre- and post-refactor code gives byte-identical output for all ten analysis artifacts and `position-replay`, differing only in `generated_at` and the one checksum derived from it.

**Locations**

| Function | Backend | Pipeline |
| --- | --- | --- |
| `clean_laps` | `backend/app/analysis/common.py:19` | `pipeline/analysis/precompute.py:339` |
| `grouped` | `common.py:38` | `precompute.py:359` |
| `trimmed_mean` | `common.py:47` | `precompute.py:367` |
| `most_common` | `common.py:55` | `precompute.py:376` |
| `lap_statistics` | `common.py:62` | `precompute.py:383` |
| `calculate_race_pace` | `race_pace.py:7` | `precompute.py:88` |
| `calculate_strategy` | `strategy.py:5` | `precompute.py:137` |
| `calculate_ideal_laps` | `ideal_laps.py:5` | `precompute.py:185` |
| `calculate_teammate_comparison` | `teammate_comparison.py:8` | `precompute.py:213` |
| `build_position_replay` | `position_replay.py:8` | `precompute.py:257` |

A third copy of the lap filter exists as `_clean_laps` at
`backend/app/analysis/advanced.py:622`.

**Reworded from the previous revision:** these are **not verbatim** copies, and
consolidation is **not trivial**. Two real obstacles:

1. **Return types differ.** The backend variants return Pydantic models —
   `calculate_race_pace` returns `RacePaceResult` and builds
   `RacePaceDriverRow` objects (`race_pace.py:7-45`); `build_position_replay`
   returns `list[PositionReplayFrame]` (`position_replay.py:8`). The pipeline
   variants return plain dictionaries so they can be serialised directly by
   `write_json` / `to_jsonable`. Sharing the code means either introducing
   Pydantic into the artifact pipeline or extracting dict-returning cores and
   wrapping them at the API boundary.
2. **Import roots are inconsistent.** `pipeline/artifacts.py:12` imports
   `backend.app.ingestion.result_validation`, while
   `backend/app/ingestion/normalizer.py:5` imports
   `app.ingestion.result_validation`. Both work (PEP 420 namespace packages;
   there is no `backend/__init__.py`), but the same source file is loaded under
   two module names, producing two distinct `InvalidSessionResultsError` classes.

**Hazard, not a demonstrated failure:** the dual identity would break any
`except` or `isinstance` that crosses the boundary. Auditing current call sites,
none does — `normalizer._results` catches the exception raised within its own
module (`normalizer.py:457-460`), and the `backend.app.*` copy invoked from
`pipeline/artifacts.py:181-182` is not caught anywhere. So this is a latent trap
that would be triggered by the very refactor recommended here.

The drift risk is real but was **overstated previously**: the only concrete
divergence found (F-18) turns out to be unreachable. `test_pipeline_parity.py`
exists specifically to police this boundary and currently passes.

**Recommended direction** Extract dict-returning cores into a shared module,
have the backend wrap them in Pydantic models, and standardise on one import
root before doing so.

**Effort** L.

**Suggested regression test** Extend `test_pipeline_parity.py` to assert both
implementations agree on a shared fixture for every duplicated function.

---

### F-13 — No CI job runs any test suite

| | |
| --- | --- |
| **Category** | Process / verification |
| **Severity** | Medium |
| **Confidence** | High |
| **Status** | **Resolved (batch 1)** |

**Resolution** Added `.github/workflows/tests.yml` with a `python` job
(`python -m pytest backend/tests -q`) and a `worker` job
(`node --test "worker/tests/*.test.mjs"`), triggered on pull requests and
pushes to `main`. Test-only dependencies live in `backend/requirements-dev.txt`
so the backend Docker image does not ship a test runner. The worker job pins
Node 24 because `node:sqlite` — used by the F-16 test — still requires
`--experimental-sqlite` on Node 22, and that test skips rather than fails when
the module is missing, so a downgrade would drop coverage silently. Both
commands are documented under *Local Development → Tests* in the README.

**Locations** `.github/workflows/` (absence); `worker/` has no `package.json`.

`frontend-ci.yml` runs `npm run lint` and `npm run build` only. Grepping
`.github/`, `README.md` and `docs/` for `pytest|unittest|node --test|npm
test|vitest` returns nothing. Unenforced: 13 test files, ~1,500 lines, including
`test_pipeline_parity.py` — the guard for F-12 — and all 31 Worker tests.

Both suites pass as of this review (31/31 Worker; 50/50 Python on the system
interpreter), which makes this the cheapest moment to lock the state in. The
absence of CI is also the proximate reason F-14, F-15 and F-16 went unnoticed.

**Recommended direction** Add a Python job (`pytest backend/tests` from the repo
root, with `backend/requirements.txt` installed) and a Worker job
(`node --test "worker/tests/*.test.mjs"`). Document both in the README.

**Effort** S.

---

### F-14 — `test_schedule_ingestion.py` depends on another test file's import side effect

| | |
| --- | --- |
| **Category** | Test infrastructure |
| **Severity** | Low (**downgraded from Medium**) |
| **Confidence** | High |
| **Status** | **Resolved (batch 1)** |

**Resolution** Added `backend/tests/conftest.py`, which inserts the repository
root and `backend/` into `sys.path` once, before pytest collects any test
module. `pytest backend/tests/test_schedule_ingestion.py` went from a
collection error to 4 passed. The per-file inserts in the other six test files
were left in place deliberately: conftest is a pytest-only hook, so removing
them would break `python backend/tests/test_x.py` direct execution.

**Locations** `backend/tests/test_schedule_ingestion.py:1-7`.

**Corrected from the previous revision.** The earlier claim that this file
"never runs" and "cannot be imported" was wrong. It is the only test file with
no `sys.path` manipulation:

| File | `sys.path.insert` lines |
| --- | --- |
| `test_backfill.py` | `parents[1]`, `parents[2]` |
| `test_local_queue_worker.py` | `parents[1]`, `parents[2]` |
| `test_pipeline_parity.py` | `REPOSITORY_ROOT`, `BACKEND_ROOT` |
| `test_fastf1_service.py`, `test_result_validation.py`, `test_session_metadata.py` | `parents[1]` |
| **`test_schedule_ingestion.py`** | **none** |

It resolves `pipeline` only because a sibling that inserts `parents[2]` (the
repository root) is imported first. `test_backfill.py` sorts first
alphabetically, so full-suite runs always work:

```
pytest backend/tests                                       -> 50 passed
pytest backend/tests/test_backfill.py \
       backend/tests/test_schedule_ingestion.py            -> 6 passed
pytest backend/tests/test_schedule_ingestion.py            -> 1 collection error:
                                    ModuleNotFoundError: No module named 'pipeline'
```

So the file runs in aggregate but cannot be run in isolation, and the suite is
one filename change or one `-k` filter away from breaking. Note also that
`python -m pytest` masks this entirely, because `-m` places the working
directory on `sys.path`.

**Recommended direction** Add the same two inserts as its siblings, or better,
add a single `backend/tests/conftest.py` that does it once and remove the
per-file boilerplate.

**Effort** S.

---

### F-15 — Two tests cannot pass on Windows: 10 ms assertions against a 15.625 ms clock

| | |
| --- | --- |
| **Category** | Test portability |
| **Severity** | Low |
| **Confidence** | High |
| **Status** | **Resolved (batch 1)** |

**Resolution** Converted the four measurement sites in
`backend/tests/test_local_queue_worker.py` from `time.monotonic()` to
`time.perf_counter()` (`QueryPerformanceCounter`, ~100 ns on Windows), with a
comment recording the resolution mismatch that caused the failures. Both tests
now pass on Windows, verified over three consecutive runs. **Correction:** the original note here claimed production could keep
`time.monotonic()` because a coarse reading "only makes it over-delay, which
is the safe direction for rate limiting". That was wrong, and the assertion
was consequently flaky (2 failures in 12 runs). `now` is subtracted from the
accumulated `_next_start`, so a stale reading *shrinks* the computed delay and
callers cluster: 4.22 ms actual spacing at a 10 ms configured interval. The
pacer now reads `perf_counter` as well. 20 consecutive runs pass.

**Locations**

- `backend/tests/test_local_queue_worker.py:270-302` (`test_request_pacer_spaces_starts_across_threads`)
- `backend/tests/test_local_queue_worker.py:170-201` (`test_r2_sync_finishes_every_body_before_starting_any_commit_marker`)

**Observable impact** In the project venv (Python 3.12.13, pinned deps):

```
FAILED ... ::test_r2_sync_finishes_every_body_before_starting_any_commit_marker
FAILED ... ::test_request_pacer_spaces_starts_across_threads
2 failed, 48 passed
```

Both fail on identical timestamps, not on wrong ordering:

```
test_request_pacer...  AssertionError: 0.0 not greater than or equal to 0.005
test_r2_sync...        AssertionError: 165279.218 not less than 165279.218
```

The cause is the clock, not the code under test:

```
monotonic     resolution 0.015625   implementation GetTickCount64()
perf_counter  resolution 1e-07      implementation QueryPerformanceCounter()
```

Both tests use `time.monotonic()` while asserting on intervals of 10 ms
(`per_second = 100.0`) and 20 ms — at or below the clock's 15.625 ms resolution
on Windows. Reproduced 3/3; this is deterministic, not flaky. The assertions are
sound on a high-resolution clock and would be expected to pass on the Linux CI
runners the workflows target.

This matters because the repository owner develops on Windows and there is no CI
(F-13), so the suite is red on the only machine that routinely runs it.

**Recommended direction** Switch both tests to `time.perf_counter()`, which is
`QueryPerformanceCounter` on Windows and monotonic in practice for interval
measurement. Optionally raise the pacer test's `per_second` so the interval
comfortably exceeds any platform's clock granularity.

**Effort** S.

---

### F-16 — The real D1 repository and the duplicate-job recovery path are untested

| | |
| --- | --- |
| **Category** | Test coverage |
| **Severity** | Low |
| **Confidence** | High |
| **Status** | **Resolved (batch 1)** |

**Resolution** Added `worker/tests/repository-d1.test.mjs`: a D1-shaped adapter
over `node:sqlite` (`prepare`/`bind`/`first`/`all`/`run` plus `batch` as one
transaction) running against the real `migrations/0001`–`0003`. Seven tests
cover `upsertSession` coalesce semantics, the `db.batch` in
`transitionJobAndSession`, the `recordArtifacts` upsert, `failStaleJobs`, and —
the two that motivated this finding — migration 0002's partial unique index
forcing `createJob` to return `null`, and a forced re-enqueue reaching the
recovery branch at `session-status.mjs:167-181`. That branch is exercised via
`force: true`, which skips both early-return guards in `enqueueIngestionJob` and
is the path the UI's "Retry ingestion" button takes.

The index pair was mutation-checked rather than assumed: with migration 0002
applied the duplicate `createJob` returns `null`; with it removed the duplicate
active job is admitted. The test detects the difference. Worker suite: 31 → 38.

**Locations** `worker/tests/*` (absence); `worker/src/repository.mjs:10-277`
(`createD1Repository`); `worker/src/session-status.mjs:167-181`.

Grepping the Worker tests for `createD1Repository`, `createRepository` or
`F1_DB` returns **nothing** — all 31 tests construct `createMemoryRepository`.
Consequently none of the actual SQL is exercised: the `db.batch` in
`transitionJobAndSession` (`:154-182`), the `on conflict` upsert in
`upsertSession` (`:33-45`), `failStaleJobs` (`:227-262`), or the interaction
between `createJob`'s `insert or ignore` (`:96`) and the partial unique index
added in `migrations/0002_prevent_duplicate_active_jobs.sql`.

That last pairing has a specific consequence. `createJob` returns `null` under
D1 when the unique index suppresses a duplicate active job, which is what makes
the recovery branch at `session-status.mjs:167-181` reachable:

```js
const job = await repository.createJob(jobRequest);
if (!job) {
  const activeJob = await repository.getActiveJob(sessionId, INGEST_SESSION);
  ...
}
```

`createMemoryRepository.createJob` (`repository.mjs:336-339`) unconditionally
stores and returns the job, so **that branch can never execute under test**. The
duplicate-active-job protection — the entire point of migration 0002 — is
unverified.

**Recommended direction** Add a small SQLite-backed or `wrangler d1 execute
--local` fixture that applies the migrations and runs the repository contract
against real SQL, and add a test that a second concurrent enqueue for one
session returns `action: "reused"`.

**Effort** M.

---

### F-17 — `createMemoryRepository()` throws when called without arguments

| | |
| --- | --- |
| **Category** | Dead code |
| **Severity** | Low |
| **Confidence** | High |
| **Status** | **Resolved (batch P2)** |

**Resolution** `createMemoryRepository` now defaults to a fresh `createMemoryState()` per call rather than a module-level singleton. All three existing callers construct fresh state per repository, so a shared singleton would have leaked state between instances; making the parameter required would only have traded a `ReferenceError` for a later `TypeError`. `createMemoryState` is intentionally not exported. Three regression tests cover no-arg construction, instance independence, and explicit state.

**Location** `worker/src/repository.mjs:279`.

```js
export function createMemoryRepository(state = memoryState) {
```

`memoryState` is not defined anywhere in the repository. Reproduction:

```
THREW: ReferenceError: memoryState is not defined
```

**Reachability: none in production.** The function is used only by
`ingestion-callback.test.mjs:8`, `ingestion-queue.test.mjs:9` and
`session-status.test.mjs:8`, all of which pass explicit state. Production
request handling always goes through `createRepository(env)` →
`createD1Repository`. This is a latent trap for the next caller, not a live
defect.

**Recommended direction** Define the module-level default, or drop the parameter
default so the argument is required.

**Effort** S.

---

### F-18 — Backend and frontend telemetry downsampling differ, unreachably

| | |
| --- | --- |
| **Category** | Consistency |
| **Severity** | Low (**downgraded from Medium**) |
| **Confidence** | High |
| **Status** | **Resolved (batch P3)** |

**Resolution** `backend/app/analysis/telemetry_compare.py` now uses `math.ceil`, so the backend caps at 300 samples as the frontend already did. Backend only -- `static-api-core.ts` was untouched.

**Locations** `backend/app/analysis/telemetry_compare.py:33`;
`frontend/src/lib/static-api-core.ts:210`.

```python
step = max(1, len(samples_a) // 300)                        # floor
```
```ts
const step = Math.max(1, Math.ceil(samplesA.length / 300)); // ceil
```

Computed across candidate lengths:

| n | backend samples out | frontend samples out |
| --- | --- | --- |
| 300 | 300 | 300 |
| 301 | 301 | 151 |
| 500 | **500** | 250 |
| 599 | **599** | 300 |
| 1200 | 300 | 300 |

**Corrected from the previous revision, which called this "live drift".** It is
not reachable. Both inputs are capped at 300 samples per lap upstream:

- `backend/app/ingestion/normalizer.py:28,488` —
  `_bounded_frame(telemetry, MAX_INGESTED_TELEMETRY_SAMPLES_PER_LAP)` with the
  constant set to 300, applied before any sample reaches
  `processed/sessions/*/dataset.json`.
- `pipeline/artifacts.py:18,254` — the published artifacts are capped at 300 as
  well. Measured: the largest committed telemetry artifact contains exactly 300
  samples (`sessions/2025-20-r/telemetry/rus-lap-50.json`).

With n ≤ 300 both expressions yield `step = 1` and identical output. The
divergence would only appear if either cap were raised.

**Recommended direction** Align on `math.ceil` for symmetry and to make the
300-sample contract hold independently of the upstream cap.

**Effort** S.

---

### F-19 — Pit-stop `lap_number` default does not guard an explicit `None`

| | |
| --- | --- |
| **Category** | Defensive correctness |
| **Severity** | Low (**downgraded from Medium**) |
| **Confidence** | High |
| **Status** | **Resolved (batch P3)** |

**Resolution** `strategy.py` and its `precompute.py` twin gained a lap-number coercion that returns `None` for unusable values; stops without a usable lap number are dropped, and a driver with only such stops is skipped rather than reaching `min()` and `int(None)`. Deliberately duplicated across both copies rather than deduplicated, to avoid pre-empting F-12.

**Locations** `backend/app/analysis/strategy.py:22-24`; duplicate at
`pipeline/analysis/precompute.py:153-155`.

```python
first_stop = min(stops, key=lambda stop: stop.get("lap_number", 999))
before = _nearest_clean_lap_time(laps, driver, int(first_stop["lap_number"]), -1)
```

`dict.get(k, default)` returns the default only when the key is **absent**. A
present-but-`None` value makes `min` compare `None` with `int` (`TypeError`), and
`int(None)` on the next line would fail regardless.

**Corrected from the previous revision.** The claim that
`normalizer._pit_stops` can emit `None` was wrong:

```python
# backend/app/ingestion/normalizer.py:379
"lap_number": _safe_int(lap.get("LapNumber"), default=0),
```

`_safe_int` (`:627-633`) returns the default on both missing and unparseable
input, so with `default=0` it returns `0`, never `None`. Additionally
`PitStop.lap_number` is a required `int` (`models/domain.py:103`), so a `None`
could not survive API validation. Measured: 0 of 1,223 committed pit stops have
a null `lap_number`.

The guard is still wrong in principle and would fail on hand-authored or legacy
data, but no current producer can trigger it.

**Recommended direction** `stop.get("lap_number") or 999`, and skip stops with no
usable lap number.

**Effort** S.

---

### F-20 — A single null `start_date` aborts scheduler candidate selection

| | |
| --- | --- |
| **Category** | Robustness |
| **Severity** | Low |
| **Confidence** | High |
| **Status** | **Resolved (batch P3)** |

**Resolution** Meetings whose `start_date` will not parse are logged and skipped instead of aborting candidate selection.

**Location** `pipeline/schedule_ingestion.py:94`.

```python
meeting_date = date.fromisoformat(str(meeting["start_date"])[:10])
```

Reproduction with one null-dated meeting:

```
ValueError: Invalid isoformat string: 'None'
-> a single null start_date aborts candidate selection entirely
```

`normalizer._event_date` (`backend/app/ingestion/normalizer.py:588-598`) can
return `None`, and the key could also be absent (`KeyError`). Measured: 0 of 46
committed meetings are affected, so this is latent. Compounds with F-10 — a
malformed catalog entry takes down the whole hourly run.

**Recommended direction** Skip meetings with an unparseable date and log them.

**Effort** S.

---

### F-21 — `body.txt` is a committed debug artifact

**Severity** Low · **Resolved (batch P1)** · Location: repository root.

**Resolution** `body.txt` removed.

Contents are a Cloudflare `302 Found` HTML error page. Delete it.

**Effort** S.

---

### F-22 — `frontend/.env.example` documents a variable that no longer exists

**Severity** Low · **Resolved (batch P1)** · Location: `frontend/.env.example:1`.

**Resolution** Rewritten to document `NEXT_PUBLIC_STATIC_DATA_BASE_PATH` and
`NEXT_PUBLIC_DYNAMIC_API_BASE_URL`, matching the root `.env.example` and the
variables the code actually reads.

It documents only `NEXT_PUBLIC_API_BASE_URL`, which appears nowhere in the
source. The frontend reads `NEXT_PUBLIC_STATIC_DATA_BASE_PATH` and
`NEXT_PUBLIC_DYNAMIC_API_BASE_URL` (`frontend/src/lib/api.ts:26,32`), both of
which are correctly documented in the root `.env.example:2-3`. Misleading for
anyone configuring hybrid mode — the exact mode F-04 and F-07 depend on.

**Effort** S.

---

### F-23 — `npm start` runs the dev server

**Severity** Low · **Resolved (batch P1)** · Location: `frontend/package.json:8`.

**Resolution** `start` is now `npx --yes serve out`, which serves the built
static export instead of duplicating `dev`. `serve` is fetched on demand rather
than declared as a devDependency.

```json
"start": "next dev --hostname 0.0.0.0 --port 3000"
```

Identical to `dev`. With `output: "export"` (`next.config.ts:5`) there is no
`next start`; the built site is a static `out/` directory. Serving `out/` (for
example `npx serve out`) or removing the script would avoid implying a
production server exists.

**Effort** S.

---

### F-24 — `_guess_session_id` cannot match name-based events

**Severity** Low · **Resolved (batch P3)** · Location:
`backend/app/ingestion/fastf1_ingestor.py:1088-1093`, used at `:1043-1045`.

**Resolution** `_guess_session_id` now returns `str | None`, resolving a
name-based event's round through the stored `processed/seasons/<year>/dataset.json`
and matching on `_slug(name)`/`_slug(official_name)`. `_slug` is imported from
`normalizer` rather than re-derived, so the rule cannot drift. No network call
was added.

For a string event it returns `{year}-{slug}-{code}`, but real session ids are
`{year}-{round:02d}-{code}`. The existence pre-check therefore never matches for
name-based events (`--event "Monaco Grand Prix"`, the form used in
`README.md:168` and `generate-artifacts.yml`), so FastF1 is reloaded every time.
Harmless — a second check follows normalization at `:1050` — but it discards the
optimisation exactly where a network round trip is most expensive.

**Effort** S.

---

### F-25 — `isEmptyState` also matches `LiveDisabledResponse`

**Severity** Low · **Confirmed (latent)** · Location:
`frontend/src/lib/static-api-core.ts:365-367`.

```ts
export function isEmptyState(value: unknown): value is EmptyStateResponse {
  return Boolean(value && typeof value === "object" && "reason" in value);
}
```

`LiveDisabledResponse` (`:398-407`) also carries `reason`, so the type predicate
is unsound. **Audited all six call sites** —
`telemetry/page.tsx:61`, `SessionTabs.tsx:265,277`,
`TelemetryComparePanel.tsx:65`, `static-api-core.ts:294,308` — every one is
passed a telemetry-comparison or position-replay value. No live response reaches
it, so this is latent type unsoundness rather than a current user-facing bug.

**Recommended direction** Discriminate on a literal tag, or check
`!("enabled" in value)`.

**Effort** S.

---

### F-26 — NaN team colour renders as `"#nan"`

**Severity** Low · **Resolved (batch P3)** · Location:
`backend/app/ingestion/normalizer.py:258`.

**Resolution** `TeamColor` is routed through `_none_if_missing`, so a NaN
colour becomes `None` rather than the string `"#nan"`.

```python
"color": f"#{color}" if color and not str(color).startswith("#") else color,
```

`float('nan')` is truthy in Python, so a NaN `TeamColor` from FastF1 produces the
literal string `"#nan"`, which flows into `Team.color` and then into inline
`style={{ backgroundColor: ... }}` (`standings/page.tsx:107`). Measured: no
committed driver record has a null or NaN team, so this is latent.

**Recommended direction** Route through the existing `_is_missing` helper.

**Effort** S.

---

### F-27 — `seriesToRows` is quadratic

**Severity** Low · **Confirmed** · Location:
`frontend/src/lib/chart-utils.ts:5-18`.

A `findIndex` runs per series per lap. At current scale (~20 drivers × ~70 laps)
this is a few tens of thousands of comparisons per render — measurable but not
user-visible. Building one `Map` keyed by `x` per series would make it linear.
Style, not urgency.

**Effort** S.

---

### F-28 — Falsy-zero guards on pace gaps

**Severity** Low · **Resolved (batch P3)** · Locations:
`backend/app/analysis/advanced.py:327,353`.

**Resolution** Both pace-gap guards now test `is not None` rather than
truthiness.

```python
row["gap_to_best_ms"] = round(row["estimated_race_pace_ms"] - best, 1) if best else None
```

`if best` treats a best pace of exactly `0.0` as missing. A lap time of zero
milliseconds is not physically realisable, so this is cleanup rather than a
defect. Prefer `if best is not None`.

**Effort** S.

---

### F-29 — A transient R2 read now silently republishes a catalog containing one session

| | |
| --- | --- |
| **Category** | Data integrity |
| **Severity** | High |
| **Confidence** | High |
| **Status** | **Resolved** |

**Resolution** Both mitigations landed. The catalog read is fail-loud by default again, with bootstrap available only under an explicit `--allow-missing-catalog` flag threaded from `pipeline/cli.py` -- a flag rather than an env var, so it cannot be inherited by every later run in the same shell or workflow. `.github/workflows/process-ingestion-job.yml` deliberately does not pass it, so the CI path stays fail-loud. Separately, `download_r2_object` now retries on the same conventions as `upload_r2_object` (`R2_DOWNLOAD_ATTEMPTS`, shared backoff, `_REQUEST_PACER`), so a blip is no longer read as absence. F-03 remains fixed: bootstrap is possible and documented in both the README and the production ingestion guide, just no longer implicit.

**Locations** `pipeline/local_queue_worker.py` — `hydrate_r2_indexes` (catalog
now `required=False`) and `download_r2_object` (no retry).

**How it got here** F-03 was correct that requiring `catalog.json` blocks the
first ingestion into an empty bucket, and the fix makes that download optional.
But `download_r2_object` treats *any* non-zero wrangler exit as absence, and
unlike `upload_r2_object` it does not retry. "The bucket has no catalog" and
"this one read failed" are now the same signal.

**Observable impact** On a bucket that does have a catalog, a single transient
`wrangler r2 object get` failure makes `merge_incremental_indexes` no-op, and
the run then publishes a catalog containing only the session just ingested —
overwriting the real index. Every other session disappears from any client
reading it. The session artifacts themselves survive in R2, so this is
recoverable by regenerating the index, but it is silent and it recurs on every
ingestion rather than only at bootstrap. F-03's failure mode was loud and
one-time; this one is neither.

The same exposure now applies to the F-06 reuse path, which hydrates the
indexes through the same helper.

**Recommended direction** Do not resolve this by string-matching wrangler's
stderr — the message is not a stable contract. Two options that are:

1. **Make bootstrap explicit.** Keep `required=True` for the catalog by
   default and allow absence only under an opt-in (`--allow-missing-catalog`,
   or an env var the first deploy sets). Bootstrap is a one-time human-initiated
   event; a normal run should still fail loudly rather than guess.
2. **Retry first, then treat absence as real.** Give `download_r2_object` the
   same bounded retry `upload_r2_object` already has. Strictly better than the
   current state and non-controversial, but it narrows the window rather than
   closing it — a persistent outage still reads as absence.

(1) closes it; (2) is a cheap partial mitigation and the two compose.

**Effort** S for either.

**Suggested regression test** Patch `subprocess.run` so the catalog read fails
while the bucket *does* contain a catalog, and assert the published catalog
still contains the pre-existing sessions.

---

### F-30 — `lap_times` is an eleventh duplication the F-12 table missed

| | |
| --- | --- |
| **Category** | Maintainability |
| **Severity** | Low |
| **Confidence** | High |
| **Status** | **Resolved** |

**Resolution** **Correction first:** the report that the two implementations differ in output was wrong. `ChartSeries` declares `metadata` with a `default_factory`, so the serialised route response already carried `metadata: {}`; both sides produce identical output. The only genuine difference was the missing `if driver.get("code")` guard, which made the route raise `KeyError` on a driver record without a code while the pipeline skipped it. This was therefore a pure move plus adopting the safer guard, not the design decision it was filed as.

The pivot now lives in `backend/app/analysis/lap_times.py`, returns dicts like the rest of the shared package, and the route wraps it in `ChartSeries` at its boundary. The parity guard covers the eleventh pair alongside the other ten, and two regression tests cover the guard and the `metadata` key. Sample artifacts regenerate byte-identically.

**Locations** `backend/app/api/routes/analysis.py:32-48` inlines the same pivot
as `pipeline/analysis/precompute.py::lap_time_series`.

F-12's table listed ten duplicated functions; this is an eleventh, and it was
not consolidated with the rest because the two are **not** a pure move. The
route emits `ChartSeries` without the `metadata: {}` key the pipeline includes,
and it reads `driver_colors` without the `if driver.get("code")` guard, so a
driver record with no `code` raises there and is skipped in the pipeline.
Consolidating means first deciding which behaviour is correct.

**Recommended direction** Treat the guard as the correct behaviour, move the
pivot into the shared analysis package alongside the other ten, and let the
route wrap the result in `ChartSeries` at its boundary as `race_pace` and
`position_replay` now do.

**Effort** S.

---

### F-31 — Dead analysis helper retained

| | |
| --- | --- |
| **Category** | Cleanup |
| **Severity** | Low |
| **Confidence** | High |
| **Status** | **Resolved** |

**Resolution** `pipeline.analysis.precompute.calculate_tyre_degradation` removed -- nothing called it, and `precompute_session_analysis` goes straight to `calculate_fuel_adjusted_tyre_degradation`. `precompute.py` is now 92 lines, from 468 before deduplication began.

The `tyre_degradation` Pydantic wrapper deliberately stays inside the analysis package rather than moving to the route: it is API-only, the pipeline never imports it, and `backend/app/analysis/__init__.py` already records it as an intentional exception alongside `qualifying_delta` and `telemetry_compare`.

**Location** `pipeline/analysis/precompute.py::calculate_tyre_degradation`.

Nothing in the repository calls it — `precompute_session_analysis` calls
`calculate_fuel_adjusted_tyre_degradation` directly. It was kept during F-12
rather than deleted, because it is a public-looking symbol and removing it is a
separate decision from deduplicating. A second, smaller instance was removed
during F-12: `precompute.linear_fit`, unreferenced and a copy of
`advanced._linear_fit`.

Note `backend/app/analysis/tyre_degradation.py` is now stylistically
inconsistent for the same reason — it is a Pydantic wrapper still inside the
analysis package, while `race_pace` and `position_replay` moved their wrapping
to the routes. It is documented as an exception in the package docstring.

**Recommended direction** Delete the dead delegation and move the
`tyre_degradation` wrapper to the route for consistency, or keep both and
accept the documented exception.

**Effort** S.

---

### F-32 — The F-02 rollback could overwrite a generation it had not fully copied

| | |
| --- | --- |
| **Category** | Data integrity |
| **Severity** | High |
| **Confidence** | High |
| **Status** | **Resolved** |

**Resolution** Raised as merge-blocking review feedback on PR #6 against the
F-02 fix itself. All three reported failure modes reproduced; all three are
fixed in `pipeline/local_queue_worker.py`.

**Location** `sync_artifacts_to_r2`, `back_up_published_session`,
`PublishedSessionBackup.restore` (`pipeline/local_queue_worker.py:327-560`).

The F-02 guard copied the live generation before overwriting it, but decided
*what* to copy using `download_r2_object(..., required=False)`, which returns
the same `False` for an object that is absent and for one whose reads all
failed. Three consequences, each demonstrated by a test that fails without the
fix:

1. **An unreadable manifest was read as a first publication.** The backup was
   skipped entirely and the live bodies were overwritten with nothing held.
   No exception was raised — the refresh reported success.
2. **A body whose backup GET exhausted its retries was silently omitted.**
   The refresh proceeded, so a later rollback restored only part of the old
   generation — the original F-02 corruption mode, reachable through the guard
   meant to prevent it.
3. **Objects only the new generation had survived a rollback.** The old comment
   called them inert because the restored manifest does not reference them, but
   the manifest is not a read index: `readOptionalSessionArtifact`
   (`frontend/src/lib/static-api-core.ts:105-118`) fetches analysis artifacts
   from fixed paths, and the Worker serves any key that exists
   (`worker/src/artifact-store.mjs` has no manifest gate). A new-only artifact
   left behind is served next to the restored generation.

The fix rests on an invariant verified against all 33 committed sessions: a
manifest's `sections` list names *every* body the generation published,
telemetry laps included. So the published manifest is a complete index of what
is live, and the backup can be exact:

- the manifest names the keys the live generation owns, and each of those is
  re-read with `required=True` — a failed read now stops the refresh before the
  first byte is overwritten, instead of leaving a hole in the backup;
- keys the new generation adds are not read at all (each was a guaranteed miss
  costing a full retry budget), and are deleted on rollback instead;
- when the manifest itself will not read, absence is no longer inferred from
  that failure. `confirm_session_is_unpublished` corroborates it against an
  index that *did* read successfully — the catalog, and the season index when
  the catalog carries that year. Only a clean read saying the session is not
  there permits the refresh; anything less certain stops it. This deliberately
  reuses `hydrate_r2_indexes`'s existing rule that a normal run fails loudly and
  only the human-initiated first deployment passes `--allow-missing-catalog`.

No Wrangler stderr text is parsed at any point.

**Residual window** The backup still lives in a temporary directory, so a runner
killed mid-restore still loses it — unchanged from F-02 and still out of scope.
One case narrows rather than closes: a session whose bodies are published but
whose index publication never completed is not in the catalog, so an unreadable
manifest for it is corroborated as absent and it may be overwritten. Reaching
that requires a previous run to have died between its manifest and its indexes
*and* the manifest to be unreadable now.

**Effort** M.

---

## 4. Corrections to the previous report

### Retained essentially unchanged

| Previous | Now | Note |
| --- | --- | --- |
| H3 | F-03 | High confirmed; reproduction added |
| M1 | F-09 | Medium confirmed |
| M3 | F-17 | Low; reachability clarified as none |
| M5 | F-13 | Medium confirmed |
| L1, L2, L3, L8, L12 | F-21, F-22, F-23, F-24, F-27 | Low, unchanged |
| L4 | F-20 | Low; reproduction added |
| L7 | F-26 | Low; confirmed latent |

### Reworded or reclassified

| Previous | Now | Change |
| --- | --- | --- |
| H1 | F-01 | Severity retained. Removed the false claim that the stale-job message blames FastF1 — it is generic. Added GitHub's `concurrency.queue: max`, which changes the recommended fix; noted the 100-pending ceiling and the `max_batch_size: 10` amplifier. |
| H2 | F-06 | **High → Medium.** The claim that the reuse path is taken for "all 33 committed sessions" was wrong: `resolveSessionStatus` returns `ready` and no job is queued, and `force` routes to the fresh branch. Reachability rewritten around the manual-Pages-deploy window. |
| H4 | F-05 | **High → Medium.** "Indefinitely" removed; staleness is bounded by browser eviction. Added the sequencing hazard with F-07. |
| M2 | F-07 | **Corrected.** 206 is *not* affected. 304 **and 416** are — 416 was missed previously. Probe table added. |
| M4 | F-14 | **Medium → Low.** The file is not dead; it passes in aggregate. The real defect is a cross-file `sys.path` ordering dependency, and `python -m pytest` masks it. |
| M6 | F-18 | **Medium → Low.** "Live drift" was wrong — the 300-sample upstream cap makes the divergence unreachable; both implementations agree on every reachable input. |
| M7 | F-19 | **Medium → Low.** The normalizer cannot emit `None` (`_safe_int(..., default=0)` → `0`). Reframed as a defensive gap with no current producer. |
| M8 | F-12 | Medium retained. "Verbatim" removed; Pydantic return types and dual import roots documented as real consolidation obstacles; dual-module exception identity marked a hazard with no demonstrated failing boundary. |
| L5 | F-10 | **Low → Medium**, but the Cloudflare Access premise was **removed as unsupported** (`docs/production-ingestion-setup.md:178,206` scope Access to `/api/ingestion/*` and state status checks are public). The confirmed defect is the fail-fast abort, now reproduced. |
| L10 | F-25 | Retained Low, reframed as latent type unsoundness after auditing all six call sites. |
| L11 | F-11 | **Low → Medium**, split into team attribution (confirmed defect, latent for the rendered year) and sprint labelling (latent — no `S` sessions committed). Data evidence added. |
| L9 | F-28 | Retained Low, explicitly reclassified as cleanup. |

### Removed as unsupported

| Previous | Reason |
| --- | --- |
| **L6** — "Inconsistent pandas-optional handling" | Not a defect. The `except ImportError` comment at `normalizer.py:13` scopes the fallback to *"metadata helpers"*. Every direct `pd.*` call (`:288-289, 611, 619`) sits inside a function that consumes a DataFrame and therefore requires pandas regardless, while `_is_missing` (`:674-682`) — the helper actually used by the pandas-free metadata functions — does guard `pd is None`. `test_session_metadata.py:63,70,111` skips exactly the pandas-dependent tests, confirming the intended boundary. The design is coherent. |
| **L13** — "Cloudflare identifiers committed in plaintext" | Unsupported. Cloudflare's Wrangler configuration documentation states it is *"best practice to treat Wrangler's configuration file as the source of truth"* and that it should be committed; `account_id` and D1 `database_id` are ordinary configuration identifiers, not credentials. Real secrets are supplied via `wrangler secret` / `.dev.vars`, and the repository already does this correctly — `wrangler.jsonc` contains no tokens, and `.dev.vars`/`.env` are excluded. |

### Newly added

| New | Summary |
| --- | --- |
| **F-02** | Non-atomic R2 refresh corrupts a published session; no read-path checksum verification exists anywhere. High. |
| **F-04** | On-demand ingestion renders a degraded dashboard — eight props missing, including a `telemetryIndex` that is fetched and then discarded. High. |
| **F-08** | FastF1 cache churn plus re-runs that are pinned to the first attempt's partial cache, undercutting the intent of commit `fc5203e`. Medium. |
| **F-15** | Two tests assert 10–20 ms spacing against `time.monotonic()`, which has 15.625 ms resolution on Windows; deterministic failure on the maintainer's own platform. Low. |
| **F-16** | Zero Worker tests exercise the real D1 repository, leaving migration 0002's duplicate-job protection and its recovery branch unverified. Low. |

---

## 5. What is working well

Verified at the cited locations during this review.

- **Worker input validation is genuinely careful.** Bounded JSON streaming with a
  `content-length` pre-check and a running byte cap
  (`worker/src/index.mjs:991-1034`); constant-time token comparison with a
  documented fallback for the missing `crypto.subtle.timingSafeEqual`
  (`:679-698`); artifact ownership bound to the job's session (`:900-913`);
  a strict public-path allowlist (`:190-192`), covered by the test
  *"private source datasets are not exposed through the public data route"*.
- **Path sanitisation is mirrored, not reimplemented by guesswork.**
  `sanitizeArtifactPath` (`session-utils.mjs:53-78`) has a deliberate Python port
  in `process-ingestion-job.yml`, explicitly labelled a diagnostic aid with the
  Worker named as the authority.
- **Manifest publication is checksum-verified before any status reaches `ready`**
  (`index.mjs:303-333` → `artifact-store.mjs:66-90`), and a verification failure
  compensates the job and session together rather than leaving a half-state.
  (F-02 concerns the *section* artifacts, which this does not cover.)
- **The job lifecycle was designed rather than accreted.** The
  `transitionJobAndSession` D1 batch (`repository.mjs:144-184`), the partial
  unique index in `migrations/0002_prevent_duplicate_active_jobs.sql` — including
  its backfill of pre-existing duplicates — and the queue-send compensation in
  `session-status.mjs:193-216` each address a real failure mode.
- **`sessionMatches` (`session-status.mjs:250-268`) avoids redundant D1 writes**
  on every status poll, and there is a test asserting exactly that.
- **Load-bearing comments explain *why*, with measurements.** `_RequestPacer`
  (`local_queue_worker.py:423-453`) documents R2's per-account rate limit and why
  worker count alone does not bound request rate; the split cache restore/save
  records that `actions/cache` declares `post-if: success()`; the concurrent
  upload block states the 28-minute serial baseline that motivated it — and
  honestly documents its own residual weakness, which is what made F-02
  straightforward to characterise.
- **The frontend build is clean.** `npm run lint` produces no output and
  `npm run build` generates 290 static pages with no TypeScript errors.
