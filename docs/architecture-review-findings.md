# Architecture review findings

## 1. Review metadata

| Item | Value |
| --- | --- |
| Repository | `aaroncchung/Formula1Data` |
| Branch | `main` |
| Commit reviewed | `4df4f0e` (merge of PR #6) |
| Review date | 2026-10-05 |
| Revised | 2026-10-05, after two reviews of the plan and seven further review rounds by GPT-6.1 Sol, the last of which passed it (section 9). AR-20, AR-21 and the publication rules, order of work and acceptance criteria in section 6 date from the revision. |
| Relationship to `docs/code-review-findings.md` | Complementary. That document reviews defects finding by finding (F-01 to F-33, all resolved). This one asks whether the architecture is the right one to keep building on. |

### Question

Should the project be restarted, given a major rewrite with architecture
changes, or patched incrementally? The project is not in production, so the
only criteria are development timeline and final product quality.

### Method

- Read in full: `pipeline/` (all six modules), `worker/src/` (all five
  modules), `migrations/`, `wrangler.jsonc`, the ingestion, scheduler and
  artifact workflows, and the frontend data layer (`static-api-core.ts`,
  `session-dashboard.ts`, `api-server.ts`) plus `SessionTabs.tsx`.
- Two independent readers, briefed without a conclusion, read all of
  `frontend/src` and all of `backend/app` plus the pipeline analysis and its
  tests. Their main claims were spot-checked against source, build output and
  committed artifacts before being used here. Claims that were not re-checked
  are marked "independent read" below.
- Ran both test suites, lint and typecheck.
- Pulled the full GitHub Actions run history and the failing step of every
  failed ingestion run.
- Measured the committed artifacts and the existing `frontend/out` build.
- Researched the available data sources and checked the main claims against
  the live endpoints (section 5).
- Read the descriptions and file lists of the four open pull requests. Their
  diffs were not reviewed line by line.
- After this document was first committed (`60687e6`), the plan was reviewed
  twice: by Claude Opus 5.5 against the code and the run history, and
  independently by GPT-6.1 Sol. Every point from both reviews was checked
  before it was applied. Section 9 lists the points and where each one landed.

### Environment

| Item | Value |
| --- | --- |
| OS | Windows 11 Pro 10.0.26200 |
| Node / npm | v24.18.0 / 11.16.0 |
| Python | `backend/.venv`, Python 3.12.14 |

### Commands run and results

| # | Command | Result |
| --- | --- | --- |
| 1 | `backend/.venv/Scripts/python -m pytest backend/tests -q` | 86 passed, 20 subtests passed |
| 2 | `node --test "worker/tests/*.test.mjs"` | 56 passed, 0 failed |
| 3 | `npx tsc --noEmit` in `frontend/` | Clean |
| 4 | `npm run lint` in `frontend/` | Clean |
| 5 | `gh run list` over all workflows (374 runs) | See AR-01 |
| 6 | `gh api .../actions/runs/{id}/jobs` for each failed ingestion run | See AR-01 |
| 7 | File counts and sizes over `frontend/out` and `frontend/public/data` | See AR-02, AR-05, AR-07 |
| 8 | Re-encoding one race's telemetry in a compact layout (scratch script, nothing written to the repo) | See AR-05 |
| 9 | Reading analysis values out of the committed 2026 race artifacts | See AR-08 |
| 10 | Requests to `livetiming.formula1.com/static` from this machine, without a token | 200 for the index, timing data, `CarData.z`, `Position.z` and `PitStopSeries`; see AR-13, AR-16 |
| 11 | Jolpica standings and results for 2026 rounds 1 to 9, compared with the committed results | See AR-15 |
| 12 | OpenF1 `pit` and `session_result` for the 2026 Australian GP, without a token | See AR-16 |
| 13 | `gh run list -R TracingInsights/2026` | See AR-13 |
| 14 | `session.get_circuit_info()` for 2026 round 8 with FastF1 3.8.3 | See AR-17 |
| 15 | Count of `drs` values in committed 2026 telemetry | See AR-18 |
| 16 | `gh run view --log` for ingestion runs 30158864535, 30159248785 and 30162384377, cache-warm runs 30163127573 and 30163198043, and successful run 28726214724 | See AR-01, AR-13 |
| 17 | `gh api .../actions/runs/{id}/logs` for the nine failed runs of 2026-07-05 | 410 Gone for all nine |
| 18 | Jolpica `2026/races.json` and `fastf1.get_event_schedule(2026)`, compared with the committed `seasons/2026.json` | See AR-20 |
| 19 | Samples per lap in the normalised dataset of `2026-08-r`; gzip of that dataset and of the session's FastF1 cache directory | See AR-11 |
| 20 | Loading the 2026 round 8 race with FastF1 3.8.3 from a copy of that one cache directory, with requests to `formula1.com` blocked | Loaded in full with no request to F1; see AR-11 |
| 21 | Building artifacts for the sample session with its telemetry removed (scratch directory), then `build_success_payload` | Quality `complete`; see AR-21 |
| 22 | Two artifact requests through PR #9's `createArtifactStore` with the pointer changed between them (in-memory bucket) | First served from generation A, second from B; see section 6, rule 1 |
| 23 | Cloudflare's R2 documentation: consistency model, S3 API extensions, pricing | See section 6, rule 2, and AR-11 |

Commands 16 to 23 were run for the revision. No repository file was modified
during the review other than this document.

### Not verified

- **A refusal from F1's servers on a GitHub runner, as an HTTP status.** The
  logs in AR-13 show every F1 feed failing on hosted runners on 2026-07-25, but
  FastF1 logs no status at that level, and nothing has been tried from a
  runner since. *Verified since: section 10.*
- **What the R2 bucket currently holds.**
- **Which Cloudflare plan the Pages project is on.** AR-02 assumes Free.
- **Anything rendered in a browser.** Chart and UI defects in AR-12 are
  deduced from code and data.
- **The nine failed runs of 2026-07-05.** Their failing step was tallied, their
  logs were not read, and the logs have since expired (command 17).
- **Independent-read reproductions.** The synthetic-input reproductions in
  AR-08 and AR-10 were run by the independent reader, not re-run here.
- **Secondary-source claims in section 5.** OpenF1's price and rate limits, the
  F1TV token requirement for live telemetry, and the coverage of the commercial
  APIs come from documentation summaries or third-party pages, not from tests.
- **Why the committed Monaco result is stale.** See AR-15.
- **The mechanisms in section 6 against the real bucket.** Conditional writes
  through R2's S3 API were checked against Cloudflare's documentation only.
  Nothing was published. *Verified since: section 10.*
- **F1's session key beyond one session.** AR-20 read it from one cached
  session. *Verified since for races and sprints: section 10.*
- **Replaying raw feed files into FastF1.** AR-11 tested FastF1's own cache
  files only.

---

## 2. Executive summary

**Recommendation: a major rewrite, scoped to the data plane.** The data plane
is everything between FastF1 and the pixels: how sessions are ingested, how
artifacts are formatted and stored, how they are published, and how a page
loads them. The analysis code and the frontend should be kept and reworked in
place. A restart is not justified.

| Layer | Assessment | Recommended fate |
| --- | --- | --- |
| Cloud ingestion (Worker job queue, D1, Actions workflow, R2 publisher) | Careful code; the system has succeeded in 2 of 118 runs | Replace with one batch command in two stages, fetch and build |
| Static path (JSON committed to git, pages built from it) | The only path that works; cannot scale | Move data to R2, load at runtime |
| Artifact format | One race's telemetry is 147 MB in 1,322 files | Change now, while re-ingesting is free |
| Python ingestion and analysis | Tidy and defensive; several analyses give misleading numbers | Keep; fix the methods |
| Frontend | Clean, strictly typed prototype with shallow pages | Keep about half; rework in place |
| Worker read path (`/data` from R2) | Solid | Keep |
| Data sources (FastF1, Jolpica, OpenF1) | The right ones; used incompletely, and ingestion runs where F1 appears to refuse requests | Keep; change where ingestion runs and what is taken from each |

**Why not restart.** The normaliser, the FastF1 loading and retry logic, the
lap filter, the frontend data layer and the UI primitives are sound and loosely
coupled. A restart would rewrite them much the same and would rediscover the
FastF1 and Cloudflare behaviour that the existing fixes encode.

**Why not incremental patches.** That is what PRs #2 to #6 were, and what
PRs #8 to #10 continued (#9 and #10 have since been closed, section 7). All of
that work is on the cloud ingestion path, which is still at 2 successes in 118
runs and is currently switched off. Patches cannot remove the four structural
causes: two competing data paths (AR-03), the deploy file cap (AR-02), the
artifact format (AR-05) and the page payload design (AR-07).

**Revised after review.** Two reviews of the plan (section 9) left the
recommendation unchanged and changed how it is carried out. The first real
end-to-end publication now comes second in the order of work instead of last.
Section 6 gains seven publication rules: consistent reads, concurrent
publishers, what counts as published, fetching kept apart from building,
session identity, completeness, and format versions. Two findings were added
(AR-20, AR-21), and AR-07, AR-11 and AR-13 were extended.

### Counts

| Severity | Count | Findings |
| --- | --- | --- |
| Critical | 1 | AR-01 |
| High | 8 | AR-02, AR-03, AR-04, AR-05, AR-08, AR-13, AR-15, AR-20 |
| Medium | 8 | AR-06, AR-07, AR-09, AR-10, AR-11, AR-12, AR-16, AR-21 |
| Low | 4 | AR-14, AR-17, AR-18, AR-19 |

---

## 3. Findings

### AR-01 — The cloud ingestion path has succeeded in 2 of 118 runs

| | |
| --- | --- |
| **Category** | System reliability |
| **Severity** | Critical |
| **Confidence** | High (GitHub Actions history) |
| **Status** | Open |

**Evidence**

`Process ingestion job` has run 118 times between 2026-07-05 and 2026-07-25.

| Outcome | Runs | Cause |
| --- | --- | --- |
| Success | 2 | Both on 2026-07-05 |
| Cancelled | 69 | Shared concurrency group evicting pending runs (F-01) |
| Failed at `Write queue message` | 35 | Bash syntax error in the workflow |
| Failed at `Process ingestion job` | 11 | 9 on 2026-07-05 (logs not read, now expired); 2 on 2026-07-25: run 30158864535 rejected its own command-line flags (fixed by PR #3), and run 30162384377 got no data from F1 (AR-13) |
| Failed at `Report ingestion success` | 1 | Run 30159248785, 2026-07-25. It republished the committed `2026-01-r` files without contacting F1, and the Worker answered the success callback with 400, `artifacts[8] has an invalid kind or path` |

Related workflows over the same period:

- `Schedule completed session ingestion`: 147 of 148 runs succeeded, but this
  workflow only submits requests to the Worker. It is now `disabled_manually`.
- `Backfill F1 data`: 8 succeeded, 10 failed. It also only submits requests.
- `Warm FastF1 cache`: 2 runs, both failed.

After the bash fix landed, three runs happened (2026-07-25). Each failed at a
different layer: the command line, the callback contract, and access to F1.
No ingestion run has happened since PR #6 merged on 2026-07-26, so the
`queue: max` fix for the cancellations and the R2 rollback work have never
executed in a real run.

Every commit that touches `frontend/public/data` (six, 2026-07-01 to
2026-07-12) was authored under the owner's git identity. None was authored by
the workflow bot, so the sessions on the site appear to come from local runs.

**Impact**

The path designed to be the production ingestion route does not deliver
sessions. Most engineering effort since 2026-07-12 has gone into it: PRs #2 to
#6, six of the 33 code-review findings, and all four open pull requests.

The site's data stops at 2026 round 9 (2026-07-05). On 2026-10-05, F1's
archive and Jolpica both held round 16 (2026-10-04).

**Recommended direction**

Replace the path rather than continue hardening it. See section 6.

---

### AR-02 — The static path reaches the Pages file cap after about five more races

| | |
| --- | --- |
| **Category** | Scalability |
| **Severity** | High |
| **Confidence** | High for the counts; the plan tier is assumed |
| **Status** | Open |

**Evidence**

- `frontend/out` contains 14,054 files, of which 10,935 are under `out/data`.
- Cloudflare Pages allows 20,000 files per site on the Free plan and 100,000 on
  paid plans (Pages limits page, checked 2026-10-05).
- Only nine sessions are fully ingested, the 2026 races for rounds 1 to 9. They
  hold 936 to 1,448 files each. The 24 races from 2025 hold 19 files each, with
  two telemetry laps apiece.
- The catalog lists 33 sessions, all races. The build generates 230 session
  routes, and 197 of them render "Session is not available".

**Impact**

At about 1,160 files per full session, the remaining 5,946 files cover about
five more races. A full 2026 season across all session types is 23 meetings
(AR-20) with five sessions each, far beyond either cap. `frontend/public/data`
is also 1.2 GB in the working tree and is checked out on every workflow run.

**Recommended direction**

Take real session data out of the deploy and out of git. Serve it from R2 and
keep only the sample dataset in the repository.

---

### AR-03 — Published data has two sources of truth and three read layers

| | |
| --- | --- |
| **Category** | Architecture |
| **Severity** | High |
| **Confidence** | High |
| **Status** | Open |

**Locations**

- `pipeline/local_queue_worker.py:109-114` (reuse path publishes the runner's
  checkout to R2)
- `pipeline/schedule_ingestion.py:14-20` (scheduler reads the committed
  `catalog.json`)
- `worker/src/artifact-store.mjs:112-135` (Worker falls back from R2 to
  `STATIC_DATA_BASE_URL`)
- `wrangler.jsonc` (`STATIC_DATA_BASE_URL` is the Pages site)

**Evidence**

Session artifacts live in git under `frontend/public/data` and, separately, in
R2. A browser can read them from Pages directly, from the Worker out of R2, or
from the Worker falling back to Pages. The publisher treats the committed
checkout as a valid source for R2, and the scheduler takes the season schedule
from the committed catalog.

**Impact**

Every publishing change has to stay correct for both stores and for the
fallback between them. Findings F-04, F-05, F-06 and F-07 and much of PR #9's
description (the "fail-open" section) are consequences of this.

**Recommended direction**

One store, R2. The Worker serves it. Nothing falls back to the static site.

---

### AR-04 — The R2 publisher compensates for its own design and has not run for real

| | |
| --- | --- |
| **Category** | Design, unvalidated code |
| **Severity** | High |
| **Confidence** | High |
| **Status** | Open. PR #9 addressed part of it and was closed as superseded (section 7) |

**Locations**

- `pipeline/local_queue_worker.py:331-451` (in-place overwrite with backup)
- `pipeline/local_queue_worker.py:454-783` (backup, restore, absence proof)
- `pipeline/local_queue_worker.py:882-971` (request pacer, upload through a
  `wrangler` subprocess per object)
- `backend/tests/test_local_queue_worker.py` (37 tests, all at the
  `subprocess.run` boundary)

**Evidence**

A publication overwrites a live session's files in place, one
`wrangler r2 object put` process per file and about 1,300 files per race. The
code itself records that this took about 28 minutes serially. Around 330 lines
then exist to back up, restore and prove absence, because `wrangler` cannot
distinguish "not found" from "read failed". Findings F-02, F-03, F-06, F-29,
F-32 and F-33 are all on this path, the last two each raised against the
previous fix.

All 37 publisher tests replace `subprocess.run` with a fake. The last
successful real run was 2026-07-05, before any of this code was written.

**Recommended direction**

Publish each generation under a new prefix and write one pointer object last,
in the layout PR #9 uses. Do not carry over PR #9's read path or its retention
rule (section 6, rule 1). Upload through R2's S3-compatible API so that a
missing object is a real 404 and a write can be conditional (rule 2). With the
format change in AR-05, a session becomes about 45 objects and the pacing
logic is no longer needed.

---

### AR-05 — The artifact format is the root of the storage and upload bulk

| | |
| --- | --- |
| **Category** | Data format |
| **Severity** | High |
| **Confidence** | High (measured) |
| **Status** | Open |

**Locations**

- `pipeline/artifacts.py:234-284` (one file per driver per lap)
- `pipeline/artifacts.py:363-369` (`indent=2`)
- `backend/app/ingestion/normalizer.py:383, 399, 420, 454` (time fields written
  as pandas `repr` strings)

**Evidence**

Telemetry for `2026-08-r`, measured on the committed files:

| Layout | Files | Size | Gzip |
| --- | --- | --- | --- |
| Current: indented JSON, one object per sample | 1,322 | 147.2 MB | 18.8 MB |
| Same rows, minified | 1,322 | 105.2 MB | not measured |
| Columnar arrays, one decimal place, bundled per driver | 22 | 23.3 MB | 8.4 MB |

Each of the 396,600 samples repeats `session_id`, `driver_code` and
`lap_number` and carries floats to 15 digits. The largest per-driver bundle is
1.25 MB. The session's `manifest.json` is 314 KB and its telemetry index is
266 KB, because both list every lap file.

Time fields reach the browser as strings such as `0 days 01:22:52.191000`.
Across the nine 2026 races this form appears 382 times in `pit-stops.json`,
244 times in `weather.json` and 151 times in `results.json`.

**Impact**

The format drives the file cap in AR-02, the upload time and rate limiting in
AR-04, and the repository size. It is cheapest to change now, since every
session can be re-ingested without a migration.

**Recommended direction**

Columnar telemetry bundled per driver, minified JSON, and times as integer
milliseconds. Write the files with a pinned newline so checksums do not depend
on the platform (PR #10 found this).

---

### AR-06 — The control plane has more hops than the job needs

| | |
| --- | --- |
| **Category** | Architecture |
| **Severity** | Medium |
| **Confidence** | High |
| **Status** | Open |

**Locations**

- `.github/workflows/schedule-ingestion.yml`, `pipeline/schedule_ingestion.py`
- `worker/src/session-status.mjs:106-227`, `worker/src/index.mjs:448-580`
- `.github/workflows/process-ingestion-job.yml` (426 lines)
- `pipeline/backfill.py:29-121` (the same job as a plain loop)

**Evidence**

A scheduled ingestion travels through eight steps: a GitHub workflow calls the
Worker, which writes a D1 job, which sends a Queue message, which the Worker
consumes, which calls GitHub `repository_dispatch`, which starts a second
workflow, which uploads to R2 and calls the Worker back, which updates D1.
GitHub calls Cloudflare in order to call GitHub.

Each hop has been a failure site. The 69 cancellations came from the queue
consumer's batch size interacting with the Actions concurrency group. One run
failed at the callback. The workflow carries three inline Python programs,
including a port of the Worker's path validator kept in YAML for diagnostics.

`pipeline/backfill.py` does the same job as a loop over the schedule in about
120 lines. Local commands of this kind, not the cloud path, appear to have
produced every session on the site (AR-01).

**Impact**

The only capability the control plane adds is ingestion requested from the
browser. The README states that this is safe only when the whole site sits
behind Cloudflare Access.

**Recommended direction**

A single idempotent batch command, run on a schedule and runnable locally:
ingest every completed session that is not yet published, as section 6
defines it (rules 3 and 4). Remove the queue, the D1 job tables, the dispatch
and the callbacks.

The queue's single consumer and the workflow's concurrency group are also the
only things that keep two publishers apart today, and neither covers a local
run. Section 6, rule 2 replaces them.

---

### AR-07 — Every tab's data is embedded in each session page

| | |
| --- | --- |
| **Category** | Frontend architecture, performance |
| **Severity** | Medium |
| **Confidence** | High |
| **Status** | Open |

**Locations**

- `frontend/src/components/session/SessionTabs.tsx:61-83` (one client
  component, 21 props)
- `frontend/src/lib/session-dashboard.ts:37-78`
- `frontend/src/app/seasons/[year]/[round]/[session]/page.tsx:8, 72-92`
- `frontend/src/lib/api-server.ts:30-52` (reads `public/data` from disk during
  the build)

**Evidence**

The 2026 race pages are 3.0 to 3.6 MB of HTML each. The page loads 20
artifacts at build time, including the 3.7 MB position replay and the 266 KB
telemetry index, and passes them all to one client component. If any of 13
required artifacts fails to load, or the default telemetry comparison does,
the whole page is replaced by an error.

The build can only produce a full page for sessions present in git at build
time. Sessions that arrive later are rendered by a second, client-side route
through `SessionIngestionPanel`. F-04 was a divergence between the two.

The session page is one of eleven build-time readers. `lib/api-server.ts` is
imported by the home page, the three season pages, the session page,
standings, strategy, telemetry, drivers, teams and circuits. Each of them
shows what was in git when the site was built. `generateStaticParams` takes
the session routes from the committed catalog with `dynamicParams` set to
`false`, so a session that was not in the catalog at build time has no route.

**Recommended direction**

A static shell that loads each tab's data from `/data` when the tab opens.
The client loader already exists (`lib/api.ts` with `loadSessionDashboard`),
and the reference branch in PR #7 prototyped the routing.

Do the same for every page that reads published data, and resolve session
routes at runtime (PR #7's `/seasons/explore` page takes year, round and
session from the query string). The build then reads no published data, and a
new session or a standings update appears without a deploy.

---

### AR-08 — Several analyses produce misleading numbers on real data

| | |
| --- | --- |
| **Category** | Analysis correctness |
| **Severity** | High |
| **Confidence** | High for the three checked on real artifacts; Medium for the rest |
| **Status** | Open |

**Checked against committed 2026 race artifacts**

| Analysis | Location | Evidence |
| --- | --- | --- |
| Pit-loss estimate | `backend/app/analysis/strategy.py:15-16` | An unbounded mean of pit-lane transit times. Round 6 reports 410,846.5 ms and round 1 reports 84,832.3 ms; the other seven rounds fall between 21,900 and 38,700 ms. |
| Undercut and overcut gain | `strategy.py:34-48` | Compares one lap before and one after the first stop with no track-status filter. The largest reported "gain" is 52,554 ms (round 2). |
| Track dominance | `backend/app/analysis/advanced.py:43-62` | In round 8, Bottas's representative lap is lap 1 at 84.016 s, against a best of 70.374 s, yet it is credited with 6 of 25 minisectors. In minisector 12 it is timed at 2,085 ms where the next car takes 4,292 ms. |

The telemetry these analyses read has already been cut to 300 samples per lap
by the normaliser (AR-11).

**Independent read, source confirmed but not re-run**

- `advanced.py:381` tests `"sprint" in normalized`, so Sprint Qualifying and
  Sprint Shootout receive the race-fuel correction.
- Tyre degradation fits are reported from three laps regardless of fit quality.
- Car performance averages samples inside fixed speed bands, so a faster corner
  can lower a car's band average.
- Team-mate comparison uses a mean over unmatched lap sets.
- `normalizer.py:616` truncates lap times to the millisecond instead of
  rounding.
- `str(value or default)` in `normalizer.py:244-308` treats NaN as present. No
  NaN literal was found in the committed session or analysis files, so this is
  latent.

**Impact**

These analyses are the product. Race pace, lap times, ideal laps and position
replay were judged sound. No analysis is tested against a recorded real
session.

**Recommended direction**

Fix each method in place and add a golden fixture from one real race. This is
local work: one function each, with no architectural dependency. Take the
fixture from the source archive (AR-11) rather than from published artifacts,
so that it survives the format change.

One fix waits for data that arrives with the new format: corner analysis from
the official corner positions in AR-17. The others can start at once,
including pit loss, which is estimated from lap times against a green-flag
baseline (AR-16) and needs no new field.

---

### AR-09 — The contract between Python and TypeScript is hand-maintained

| | |
| --- | --- |
| **Category** | Type safety |
| **Severity** | Medium |
| **Confidence** | Medium (independent read) |
| **Status** | Open |

**Evidence**

- The normaliser and the pipeline pass `dict[str, Any]` throughout. The
  Pydantic models in `backend/app/models/domain.py` are used only by the
  FastAPI routes.
- `frontend/src/types/domain.ts` (395 lines) is written by hand. For the
  advanced analyses it is the only schema that exists.
- Drift has already occurred: the Python `TyreDegradationResult` carries
  `model` and `caveats`, and the TypeScript type does not.
- `schema_version` is written into the catalog, the season indexes, each
  session manifest and each telemetry index (`pipeline/artifacts.py:60, 121,
  165, 213, 276`) and never checked. The session sections, analyses, replay
  and telemetry lap files carry no version.

**Recommended direction**

Define the artifact shapes once as Pydantic models at the write boundary and
generate the TypeScript types from them. Do this together with AR-05, since
the format is changing anyway.

---

### AR-10 — A third of `backend/app` is reachable only through an unused API

| | |
| --- | --- |
| **Category** | Dead code, packaging |
| **Severity** | Medium |
| **Confidence** | Medium (independent read; import structure confirmed here) |
| **Status** | Open |

**Evidence**

- About 19 files and 1,130 lines of `backend/app` are reachable only through
  FastAPI: the routes, `main.py`, the response models, three analysis modules,
  the OpenF1 code and the cache service. Every route loads every session
  dataset, which is 1.4 GB today.
- The pipeline imports analysis as `backend.app.*`
  (`pipeline/analysis/precompute.py:14-38`) and ingestion as `app.*` through a
  `sys.path` insertion (`pipeline/cli.py:221-226`,
  `pipeline/backfill.py:41-47`, `pipeline/local_queue_worker.py:1328-1333`).
  The same module can therefore load twice under two names.
- `configure_backend_data_dir` is defined three times, and the `sys.path`
  insertion that makes `app.*` importable appears three times.
- The tests for the pipeline live under `backend/tests`.

**Recommended direction**

Delete the API shell and `backend/scripts`. Move ingestion, normalisation and
analysis into one package with one import root.

---

### AR-11 — Rebuilding artifacts deletes every committed session not held locally

| | |
| --- | --- |
| **Category** | Data safety |
| **Severity** | Medium |
| **Confidence** | High (read, not executed) |
| **Status** | Open |

**Locations**

- `pipeline/artifacts.py:43, 304-307` (`reset_directory` removes the output
  directory)
- `pipeline/cli.py:130-152`
- `.gitignore:19-20` (`backend/data/processed/sessions/` is ignored)

**Evidence**

`build_static_artifacts` deletes its output directory, which defaults to
`frontend/public/data`, and rebuilds it from `backend/data/processed`. That
source directory is ignored by git. On this machine it is 1.4 GB across 33
sessions; on any other checkout it holds only the sample.

The first command in the README's Local Development section,
`python -m pipeline generate --sample`, therefore replaces all 33 committed
sessions in the working tree with the sample. `ingest-session` on a fresh
clone leaves only the session just ingested.

**The source data** (added in the revision)

- Everything needed to rebuild the 33 sessions is on this machine only:
  `backend/data/cache/fastf1` (3.5 GB) and `backend/data/processed` (1.4 GB),
  both ignored by git.
- The normalised dataset is not the source. The normaliser keeps at most 300
  telemetry samples per lap (`normalizer.py:28, 490`). Each of the 1,322 laps
  in `2026-08-r` holds exactly 300; FastF1 returns 557 for the one lap
  compared, Norris's fastest. The dataset also carries the string times of
  AR-05 and the lap-time truncation of AR-08.
- FastF1's cache directory for that race is 84 MB, or 13.8 MB gzipped. The
  normalised dataset is 186 MB, or 19.6 MB gzipped. At the cache's size, a
  season of every session type is under 2 GB of R2's 10 GB free allowance.
- The cache directory is enough to rebuild from. With a copy of it alone and
  requests to `formula1.com` blocked, FastF1 3.8.3 loaded 1,339 laps, car data
  for 22 of 22 drivers, weather and race control, and attempted no request to
  F1. It contacted only Jolpica and FastF1's schedule file on GitHub
  (command 20).
- The cache files carry FastF1's cache version, 15 in 3.8.3
  (`fastf1/req.py:205, 495`). FastF1 discards files written under another
  version.

**Impact**

The committed artifacts can be regenerated on one machine only. The loss is
recoverable with `git checkout`, but an unnoticed commit would remove the data
from the site.

**Recommended direction**

Resolved by AR-03: with R2 as the only store, a local build writes to a
scratch directory and publishing is a separate, additive step.

Keep each session's source data in R2 as well, in the form it arrived in:
FastF1's cache directory for the session, compressed, rather than the
normalised dataset. Upstream access has tightened repeatedly: live telemetry
moved behind a login in 2025, the 2026 feed carries no aero or ERS data
(AR-18), and cloud addresses appear to have been refused since July 2026
(AR-13). Data that may not be re-fetchable should not exist on one machine
only. Copy the existing cache to R2 before any other work (section 6, step 1).

Build artifacts from that archive and from nothing else (section 6, rule 4).
Fetching is then the only stage that needs a network F1 answers, and the
analysis fixes in AR-08 can be rebuilt on any machine. Pin FastF1, and treat
a release that changes its cache version as a re-fetch. Keeping the raw feed
files too would remove that dependency; it was not tested.

---

### AR-12 — The frontend is a clean prototype with shallow pages

| | |
| --- | --- |
| **Category** | Frontend quality |
| **Severity** | Medium |
| **Confidence** | Medium (independent read; items marked * confirmed here) |
| **Status** | Open |

**Done well**

- The data layer takes an injected reader, so the same API serves the build
  and the browser, and failures are a discriminated result type.
- TypeScript is strict, with no `any`, no non-null assertions and no
  suppressions.
- Components are small, and `DataTable`, `ChartPanel` and the badges are
  reused consistently.
- Empty states and method caveats are surfaced honestly.

**Weaknesses**

- `/live` prints the payload as JSON in a `<pre>` block
  (`LiveTimingBoard.tsx:14-17`) *. `/settings` is hard-coded text.
- `/strategy`, `/telemetry`, `/drivers` and `/teams` are pinned to the most
  recent session.
- The weather chart's X axis is `lap_number` (`WeatherTimeline.tsx:13`), which
  is null in all 30 samples of `2026-08-r` *.
- The pit-stop table shows the pandas string from AR-05 as "Local time" *.
- The build machine's absolute path is baked into the 197 "not available"
  pages through `api-server.ts:50` *.
- The tyre chart keeps the first eight drivers; team-mates share a line
  colour; the position replay has no fixed domain.
- `SessionIngestionPanel` resets its polling on every poll, and one transient
  error ends it. PR #8 addresses part of this.
- About 250 lines are dead or duplicated, including `qualifyingDelta` and
  `components/forms/Selectors.tsx`.
- There are no frontend tests on `main`. PR #8 adds a runner.

**Recommended direction**

Rework in place. Roughly half is expected to survive: most of `lib/`, the
types and the primitives. The chart components and the page composition need
the most work. None of it is entangled.

---

### AR-13 — F1's timing archive appears to refuse cloud addresses since mid-July 2026

| | |
| --- | --- |
| **Category** | External dependency |
| **Severity** | High |
| **Confidence** | High that hosted runners could not read the archive on 2026-07-25. Medium that this is a deliberate refusal and still in force: no HTTP status was logged, and nothing has been tried since |
| **Status** | Confirmed 2026-10-05: HTTP 403 from F1's CDN on a hosted runner (section 10). Fetching runs on a local machine (decision 2) |

**Evidence**

- **This project, after the change.** Three runs on GitHub-hosted runners on
  2026-07-25 started with an empty FastF1 cache: ingestion run 30162384377
  (2026 round 1) and cache-warm runs 30163127573 (2026 round 1) and
  30163198043 (2024 round 9). In each, all six feeds FastF1 asks for first
  (session info, driver list, session status, lap count, track status and
  timing data) failed on each of three attempts, about half a second apiece,
  and the run ended with `FastF1 session.load returned without populated
  laps`. FastF1 logs no HTTP status at that level. These logs expire about
  2026-10-23. A fourth run that day, 30159248785, got past ingestion only
  because it republished committed files and never contacted F1 (AR-01).
- **This project, before the change.** Run 28726214724 on 2026-07-05, also on
  a hosted runner (`ubuntu-24.04`) and also with FastF1 3.8.3, fetched every
  feed of a 2024 race from an empty cache.
- **Jolpica was not affected.** The failing runs still finished with the full
  driver list. FastF1 takes that list from Jolpica when F1's driver feed fails
  (`fastf1/core.py`, the "only Ergast data" branch), so Jolpica answered the
  runner that F1 did not.
- **Another cloud platform.** FastF1 discussion #949 (2026-07-18) reports HTTP
  403 from `livetiming.formula1.com` on Google Colab while the same URL
  returned 200 from another network. A respondent attributes it to F1's CDN
  refusing that runtime.
- **Another project.** `TracingInsights/2026`, a public archive built with
  FastF1, ran its session workflows on `ubuntu-latest`. Of its 32 session runs
  since 2026-07-17 (FP1 25, FP2 3, FP3 1, Q 1, R 2) none succeeded. The
  repository is still updated (last push 2026-10-04), so its data is now
  produced somewhere else. Its logs have expired and could not be read.
- **A residential network.** From this machine on 2026-10-05, the archive
  answered 200 without a token for the index, timing data, `CarData.z` and
  `Position.z` of a 2026 session.

**Impact**

FastF1 reads F1's archive directly, so it works only from a network that F1
answers. GitHub-hosted runners appear not to be one. This is consistent with
AR-01: the sessions on the site appear to have been ingested locally.

No architecture removes this. It decides where fetching can run, so it should
be settled first. Only fetching is affected: Jolpica answers hosted runners,
and FastF1 loads a session from its cache without contacting F1 (AR-11).

**Recommended direction**

Confirm with a real ingestion, not a single request. On a GitHub-hosted runner
with an empty cache, ingest one completed session, assert populated laps and
car and position data for every driver (AR-21), and log the HTTP status of each failed
request. A 200 for `Index.json` would not show that the timing and telemetry
feeds answer.

If it is refused, run the fetch stage on a self-hosted runner or as a
scheduled task on a local machine; building and publishing can stay on hosted
runners (section 6, rule 4). OpenF1 and the TracingInsights archive are hosted
independently of F1's archive and are the fallbacks if neither is acceptable,
at the cost described in section 5.

---

### AR-14 — The Worker carries code and tables nothing reads

| | |
| --- | --- |
| **Category** | Dead code |
| **Severity** | Low |
| **Confidence** | High |
| **Status** | Open; mostly removed by AR-06 |

- The D1 tables `artifacts` and `live_snapshots` are written
  (`worker/src/repository.mjs:199-225, 264-275`) and never queried.
- `getSessionByLookup` and `incrementJobAttempts` have no callers.
- `createMemoryRepository`, a test double, ships in `worker/src/repository.mjs`.
- `GET /api/session-status` writes to D1 (`session-status.mjs:37-39, 62-64`).

---

### AR-15 — The standings on the site are wrong for 12 of 22 drivers

| | |
| --- | --- |
| **Category** | Data correctness |
| **Severity** | High |
| **Confidence** | High (compared with Jolpica on 2026-10-05) |
| **Status** | Open |

**Locations**

- `frontend/src/app/standings/page.tsx:19-85` (sums points over ingested
  sessions)
- `backend/app/services/fastf1_service.py:112-147` (classification refresh at
  ingestion time only)

**Evidence**

The standings page adds up `points` across the race and sprint sessions in the
catalog. Only races are ingested.

Summing the committed results for 2026 rounds 1 to 9 and comparing them with
Jolpica's standings after round 9:

- 12 of 22 drivers differ. `ANT` shows 158 points against an official 179.
  `HAM` (129) is placed ahead of `RUS` (128), where officially `RUS` (154)
  leads `HAM` (147).
- Four sprints fall in those rounds (2, 4, 5 and 9). None is ingested, and
  together they carry 144 points.
- With the sprint points added, five drivers still differ, all from round 6
  (Monaco). The committed result has `GAS` third with 15 points. Jolpica has
  him seventh with 6, and `HAD`, `PIA`, `LAW` and `LIN` each one place higher.
  The cause was not determined: either the classification changed after the
  session was ingested, or the refresh from Jolpica did not apply.

**Impact**

Standings derived from ingested sessions are right only if every
points-scoring session is ingested and no result changes afterwards. Neither
holds today.

**Recommended direction**

Take driver and constructor standings from Jolpica. FastF1 already wraps both
(`get_driver_standings` and `get_constructor_standings` are present in 3.8.3).
Ingest sprints. Re-fetch the classification of recent rounds on every run so
that penalties applied after a race are picked up.

---

### AR-16 — Stationary pit-stop times are available and unused

| | |
| --- | --- |
| **Category** | Data source coverage |
| **Severity** | Medium |
| **Confidence** | High |
| **Status** | Open |

**Locations**

- `backend/app/ingestion/normalizer.py:330` (`_pit_stops`)
- `backend/app/analysis/strategy.py:15-16`
- `README.md:481` ("Pit duration is total pit-lane transit ... not stationary
  service time")

**Evidence**

- The project records one duration per stop, the pit-lane transit time.
- F1's archive publishes a `PitStopSeries` feed for each race that carries
  both figures. For the 2026 Australian GP it was readable without a token;
  one entry reads `PitStopTime` 2.9 and `PitLaneTime` 18.266.
- FastF1 3.8.3 does not parse this feed. It is absent from
  `fastf1._api.pages`.
- OpenF1's `pit` endpoint exposes the same pair as `stop_duration` and
  `lane_duration`. For the same race, 20 of 36 rows carry `stop_duration`
  (median 3.3 s) and the median `lane_duration` is 19.1 s. OpenF1 documents
  `stop_duration` as available from the 2024 United States GP.
- The same archive also carries `OvertakeSeries` and `TyreStintSeries`, which
  marks new and used tyre sets.

**Recommended direction**

Parse `PitStopSeries` during ingestion. It is a small line-delimited JSON
stream on the host FastF1 already reads. Store both durations and show them as
what they are, stationary time and pit-lane time.

Neither is pit loss. Pit loss is the time a stop costs against staying out,
and lane time has no on-track baseline in it. Estimate it per stop as the
in-lap plus the out-lap, minus twice the driver's median clean lap in the
laps around the stop, for stops made under green only. Report the median
across stops. Where too few stops qualify, show no estimate (AR-08).

---

### AR-17 — Corners are inferred although official corner data is available

| | |
| --- | --- |
| **Category** | Data source coverage |
| **Severity** | Low |
| **Confidence** | High |
| **Status** | Open |

**Evidence**

- `calculate_corner_analysis` (`backend/app/analysis/advanced.py:100-153`)
  infers corners from brake application and speed loss and numbers them in
  detection order. Its own caveat says they are "not official circuit
  geometry".
- `session.get_circuit_info()` in FastF1 3.8.3 returned, for 2026 round 8
  (Austrian GP), 10 corners with number, letter, coordinates and angle, 16
  marshal sectors and the track rotation. With telemetry loaded it also gives
  each corner's distance along the lap. FastF1 takes this from the MultiViewer
  API.

**Recommended direction**

Segment laps by the official corner positions, and keep the inferred method
only as a fallback when circuit information is missing.

---

### AR-18 — The DRS channel is empty for 2026 and nothing replaces it

| | |
| --- | --- |
| **Category** | Data source coverage |
| **Severity** | Low |
| **Confidence** | High |
| **Status** | Open |

**Evidence**

- `drs` is 0 in all 240,000 samples checked, the first 400 lap files of 2026
  rounds 1 and 8. In a 2025 race it takes both values.
- The 2026 regulations removed DRS. The FastF1 maintainer wrote on 2026-03-14
  that "F1 has decided to not make any data on active aero and ERS state
  available publicly."
- Every source in section 5 draws on the same feed, so none carries it.
- The field is stored in every telemetry sample and in the comparison payload
  (`drs_a`, `drs_b`). No chart reads it.

**Recommended direction**

Omit the channel for 2026 onwards as part of the format change (AR-05), and do
not plan features around aero or energy data.

---

### AR-19 — Live mode cannot authenticate against OpenF1 as written

| | |
| --- | --- |
| **Category** | Integration |
| **Severity** | Low (live mode is disabled and the page is a stub) |
| **Confidence** | High for the header; Medium for price and limits (secondary sources) |
| **Status** | Open |

**Locations**

- `worker/src/index.mjs:423-446`
- `backend/app/services/openf1_service.py`
- `frontend/src/components/live/LiveDataPanel.tsx:36-42, 80-86`

**Evidence**

- The Worker sends the configured key as an `x-api-key` header
  (`index.mjs:430-432`).
- OpenF1 authenticates with a bearer token obtained by posting a username and
  password to `https://api.openf1.org/token`. Tokens last one hour. Its
  documentation mentions no `x-api-key` header.
- OpenF1's historical data is free. Real-time data needs a paid account,
  reported at about 9.90 euros a month, and the free tier is reported as 30
  requests a minute.
- The live page polls five Worker routes every four seconds, which is seven
  upstream requests per cycle behind a three-second cache.
- `backend/app/ingestion/openf1_ingestor.py` has no callers.

**Recommended direction**

If live timing is built, authenticate with a bearer token and subscribe to
OpenF1's MQTT or WebSocket stream instead of polling. Otherwise remove the
live routes (decision 4).

---

### AR-20 — Session identity follows round numbers, and the 2026 calendar has changed

| | |
| --- | --- |
| **Category** | Data identity |
| **Severity** | High |
| **Confidence** | High (schedules compared on 2026-10-05) |
| **Status** | Open (added in the revision) |

**Locations**

- `backend/app/ingestion/normalizer.py:144-145` (`session_id` and
  `meeting_id` built from the round number)
- `pipeline/backfill.py:141`, `backend/app/ingestion/fastf1_ingestor.py:80`
  (the same key decides whether a session is already ingested)
- `frontend/src/app/seasons/[year]/[round]/[session]/page.tsx:10-12` (the
  route is mapped back to the same key)
- `frontend/public/data/seasons/2026.json` (schedule generated 2026-07-13)

**Evidence**

- A session is identified as `{year}-{round}-{session}`, for example
  `2026-16-r`, in storage paths, in the "already ingested" check and in page
  routes.
- The committed 2026 schedule lists 22 rounds, with Singapore as round 16 on
  2026-10-11.
- On 2026-10-05, FastF1 and Jolpica both list 23. Round 16 is now a race on
  2026-10-04 at Sepang (FastF1: "Bahrain Grand Prix", Kuala Lumpur; Jolpica:
  "Bahrain Grand Prix in Malaysia"). Singapore is round 17, and every later
  round has moved by one.
- Nothing after round 9 is ingested, so no published session is misfiled yet.
  The season page has no entry for the new race and numbers the seven races
  after it one too low.
- F1's own session information carries identifiers that do not depend on
  calendar order. For the 2026 round 8 race, the cached session info holds
  session `Key` 11315 and meeting `Key` 1288.

**Impact**

In the target architecture this key names the R2 prefix and decides whether a
session is already published. After a calendar change the job would treat a
different race as published, or file a new race under an old one's key. A
page route built from a schedule snapshot goes stale in the same way.

**Recommended direction**

Identify a published session by F1's session key, and carry year, round and
names as attributes in the index. Refresh the schedule on every run and
publish it as data, so that round numbers are looked up and not baked in
(section 6, rule 5). Confirm in step 3 that the key is present for every
session type.

---

### AR-21 — A session with no telemetry is ingested and reported complete

| | |
| --- | --- |
| **Category** | Data completeness |
| **Severity** | Medium |
| **Confidence** | High (executed on the sample session) |
| **Status** | Open (added in the revision) |

**Locations**

- `backend/app/services/fastf1_service.py:83-102` (telemetry, weather and
  messages are loaded in a second call whose failure is caught)
- `pipeline/artifacts.py:272-283` (the telemetry index is written even when it
  lists no laps)
- `pipeline/local_queue_worker.py:288-323` (quality is derived from which
  artifact kinds exist)

**Evidence**

- Only laps are required. If the second load raises, the service prints
  "Continuing with required lap data only" and ingestion proceeds.
- The artifact writer then produces `telemetry/index.json` with an empty lap
  list.
- `build_success_payload` marks a session `partial` when an expected artifact
  kind is absent, and the empty index counts as present. With the sample
  session's telemetry removed, the result was quality `complete` with nothing
  missing (command 21).

**Impact**

A partial refusal by F1, with timing answered and car data not, would produce
a session whose telemetry tab and telemetry-based analyses are empty, recorded
as complete. A job that skips published sessions would never retry it. The
same gap would let the probe in AR-13 pass on a runner that cannot fetch
telemetry.

**Recommended direction**

Measure coverage when a session is fetched, per driver and per feed: the share
of laps with car data and, separately, the share with position data. One
figure for "telemetry" is not enough. When the merged telemetry fails,
`_lap_telemetry` falls back to car data alone (`normalizer.py:512-528`); those
laps count as having telemetry but carry no coordinates, and the position
replay drops them (`position_replay.py:15-20`).

Check the timing itself as well, and take the shares against the laps
expected, not the laps loaded. The loader requires only that laps are not
empty (`fastf1_service.py:96-102`), and `validate_final_results` checks the
classification without comparing it to the timing
(`result_validation.py:10-40`). A race cut to one lap per driver passes both.
For races and sprints, reconcile each driver's lap count with the
classification. Add a test on a recorded race with its timing truncated and
its classification intact. Record the figures with the session. Treat a session below the bar as not yet complete and fetch it again
on later runs, from an empty cache. Publish it as partial, with the gap shown
on the page, only once a retry window has passed (section 6, rule 6).

---

## 4. What is working well

- **Worker request handling.** Bounded JSON reads, constant-time token
  comparison, a strict public-path allowlist, and correct conditional and range
  responses from R2 (`worker/src/artifact-store.mjs`). The read path should be
  kept nearly as it is.
- **FastF1 ingestion.** Staged loading with backoff, a cross-check of results
  against the authoritative classification, and strict validation of final
  results before anything is published.
- **Normaliser structure.** Eight section builders and a set of coercion
  helpers, with incomplete sessions raising a specific error.
- **Analysis code shape.** Pure standard library, small functions (median seven
  lines), consistent guards for empty input and zero denominators. The methods
  need work (AR-08); the scaffolding does not.
- **Frontend hygiene.** See AR-12.
- **Engineering discipline.** Comments explain why, with measurements. Both
  suites run in CI. The code-review findings were closed with regression tests.

---

## 5. Data sources

Every telemetry source available for Formula 1 draws on one upstream, F1's own
live-timing service. Choosing between them is a choice of wrapper and of
access path, not of data: no source offers car telemetry beyond what that feed
carries, and the commercial feeds offer less.

**Conclusion.** The three sources in use are the right ones. They are used
incompletely (AR-15 to AR-18), one is integrated incorrectly (AR-19), and where
ingestion runs matters more than which source it uses (AR-13).

### In use

| Source | Used for | Assessment |
| --- | --- | --- |
| FastF1 3.8.3 | Schedule; laps, telemetry, weather and race control for every ingested session | The right choice. 3.8.3 (2026-04-29) is the current release. It does the lap alignment, distance integration and lap-accuracy checks that the alternatives leave to the caller. Constrained by AR-13. |
| Jolpica-F1, through `fastf1.ergast` | Final race and sprint classification | The right choice, and under-used (AR-15). Limits are 4 requests a second and 500 an hour. It held the 2026-10-04 race on 2026-10-05, and it answered GitHub-hosted runners on the day F1's archive did not (AR-13). |
| OpenF1 | Live proxy in the Worker, disabled | The right choice for live timing. The integration cannot authenticate (AR-19). |

### Alternatives assessed

| Source | Provides | Limits | Verdict |
| --- | --- | --- | --- |
| F1 static archive, read directly | Feeds FastF1 does not parse: stationary pit stops, overtakes, tyre stints | Undocumented; same refusals as FastF1 | Use for pit stops only (AR-16) |
| OpenF1, for history | Raw telemetry and timing since 2023, stationary pit times, session results, starting grid, overtakes | Free tier reported as 30 requests a minute; no lap-aligned telemetry or distance, so FastF1's processing would have to be rebuilt | Fallback only |
| TracingInsights archive on GitHub | FastF1 output per lap, published about 30 minutes after each session, Apache-2.0 | One small third-party project (26 stars) whose own runner ingestion stopped working (AR-13); its schema, not ours | Fallback only |
| F1DB | All-time results, qualifying, practice, sprints, pit stops, standings and circuit layouts since 1950; CC BY 4.0; released after each race | No telemetry | Optional, for all-time history pages |
| F1 live SignalR feed | Live timing; live car telemetry and positions reported to need an F1TV token since the 2025 Dutch GP | Undocumented; needs a persistent connection | Not worth it over OpenF1 |
| Sportradar, Sportmonks, API-Sports | Results, lap times, pit stops, standings | Paid (Sportmonks from 55 euros a month; Sportradar by contract); no car telemetry | No |

### Recommended changes

1. Keep FastF1 as the primary source and fetch with it from a network F1
   answers (AR-13).
2. Take standings and final classifications from Jolpica, re-fetch recent
   rounds on every run, and ingest sprints (AR-15).
3. Parse `PitStopSeries` for pit stops (AR-16).
4. Use `get_circuit_info()` for corners (AR-17).
5. Drop DRS from 2026 sessions (AR-18).
6. Keep each session's source data in R2 as FastF1 cached it, and build from
   that archive (AR-11).
7. If the live page is built, pay for OpenF1 and use its stream (AR-19).
8. Identify sessions by F1's session key and refresh the schedule on every run
   (AR-20).
9. Check car-data and position-data coverage before a session counts as
   complete, and retry from an empty cache (AR-21).

### External sources

- FastF1 release notes: <https://docs.fastf1.dev/changelog/index.html>
- FastF1 discussion #949, 403 from a cloud runtime:
  <https://github.com/theOehrly/Fast-F1/discussions/949>
- FastF1 discussion #861, 2026 ERS and aero data:
  <https://github.com/theOehrly/Fast-F1/discussions/861>
- FastF1's Jolpica interface and rate limits:
  <https://docs.fastf1.dev/api_reference/jolpica.html>
- OpenF1 documentation: <https://openf1.org/docs/>
- OpenF1 authentication: <https://openf1.org/auth.html>
- OpenF1 price and free-tier limits (third-party comparison):
  <https://ocblacktop.com/guides/free-formula-1-api-comparison>
- Jolpica-F1: <https://github.com/jolpica/jolpica-f1>
- TracingInsights 2026 archive: <https://github.com/TracingInsights/2026>,
  <https://mintlify.wiki/TracingInsights/2026/data-sources>
- F1DB: <https://github.com/f1db/f1db>
- F1TV token requirement for live telemetry (third-party project):
  <https://github.com/harsh779/f1-live-api>
- Sportradar Formula 1 API:
  <https://developer.sportradar.com/racing/docs/f1-ig-overview>
- Sportmonks Formula One API: <https://www.sportmonks.com/formula-one-api>
- Cloudflare Pages limits:
  <https://developers.cloudflare.com/pages/platform/limits/>
- Cloudflare R2 consistency model (last writer wins on one key):
  <https://developers.cloudflare.com/r2/reference/consistency/>
- Cloudflare R2 S3 API extensions and conditional `PutObject` headers:
  <https://developers.cloudflare.com/r2/api/s3/extensions/>,
  <https://developers.cloudflare.com/r2/examples/aws/custom-header/>
- Cloudflare R2 pricing and free allowance:
  <https://developers.cloudflare.com/r2/pricing/>

---

## 6. Recommended architecture

### Target

```text
F1 archive --> fetch -----------> source archive --> build ----------> R2 (only store)
               (scheduled, on a   in R2 (FastF1      (any machine;     generation prefix
                network F1         cache per          typed, compact    per publish,
                answers)           session)           artifacts)        pointer written last
Jolpica -----------------------------------------------^                     |
                                                                             |
browser <--- static shell, every page loads at runtime, <--- Worker /data ---+
             one generation per session view
```

### Publication rules

These rules apply to everything in the target. Each one closes a gap found
when the plan was reviewed (section 9).

1. **A session view reads one generation.** The page reads the session's
   pointer once and then requests every artifact by its generation path.
   Generation paths never change, so they can be cached as immutable; only the
   pointer and the index need a short cache life. The Worker serves keys as
   given and resolves nothing.

   PR #9's Worker resolved the pointer again for every artifact request
   (`worker/src/index.mjs:164` on that branch builds one store per request).
   With the pointer changed between two requests, `summary.json` came from one
   generation and `laps.json` from the next (command 22). Loading tabs on
   demand keeps that window open for as long as the page is.

   Keep a superseded generation for a set period, not a set count. PR #9 keeps
   one previous generation, so a view that outlives two publications loses its
   files. On a 404 for a pinned generation, the page reads the pointer again
   and reloads the session. Do not build pruning until the publish path has
   run for real; the first version of it in PR #9 had a data-loss bug.

2. **Every object that changes is written conditionally.** The pointer, the
   index and the standings are written with `If-Match` on the version that was
   read, or `If-None-Match: *` when there was none. Generations and archive snapshots need no guard: each is
   written once under a new name.

   The guarded read comes first. For each attempt the job reads the object
   and its version, then gathers everything the new content is derived from,
   then writes against that version. For the index that order is: read the
   index, list the pointers, derive, write. Listing before the read would let
   another publisher's pointer and index land in between, and the write would
   then succeed and drop that publisher's session with no conflict raised.

   A conflict means another publisher got there first, so the job does not
   resend what it built. It reads the object again and decides again from
   current inputs. For a pointer it applies rule 3 to the pointer now in
   place: if the session no longer needs a rebuild, the candidate generation
   is dropped; if it does, the candidate is published only when it was built
   by this pipeline version from the snapshot and classification rule 3 would
   select now, and is rebuilt otherwise. A job never replaces a pointer whose
   pipeline version is newer than its own, with or without a conflict, so a
   run from an old checkout cannot undo a newer one. For the index, the job
   starts the whole sequence again from the read. For standings, it reads
   the stored copy, fetches from Jolpica again without a cache, and writes
   what it fetched if the content differs and covers the same round or a
   later one. A correction within a round therefore replaces the stored copy,
   and a slow run cannot move the standings back a round.

   This replaces the queue and the workflow concurrency group, which keep
   publishers apart today (AR-06). The current publisher reads the catalog and
   season index from R2, merges them and writes them back
   (`pipeline/local_queue_worker.py:786, 1160`). Two overlapping runs can each
   drop the other's session, because R2 lets the last writer win. The store
   enforces the rule, so it also holds for a run started by hand. A lock was
   considered and not chosen: it needs an expiry and a takeover rule, and the
   conditional write is needed in any case.

3. **"Published" is read from R2, and the index is derived.** A session is
   published when its pointer exists. Pointers live under one prefix, so the
   published set is one list call. The index (the catalog and season lists) is
   rebuilt on every run from that list and the current schedule. It is never
   merged from files on the machine that runs the job, which is how today's
   "already ingested" check and catalog work (`pipeline/backfill.py:88`,
   `pipeline/artifacts.py:73-105`). A lost or failed index write is then
   corrected by the next run.

   The pointer records the generation, the format version, the pipeline
   version, the archive snapshot it was built from, a fingerprint of the
   classification it used, and the coverage (rule 6). A session is rebuilt
   when it has no pointer, when its pipeline version is older than the
   code's, when its classification has changed, or when the snapshot rule 6
   selects is not the one the pointer names. The last condition is what
   replaces a partial publication once a later fetch does better.

   Published and complete are separate states. A session with a pointer is
   published; it is complete only when the pointer's coverage meets the bar.
   The job skips fetching only for complete sessions.

4. **Fetching and building are separate stages.** Fetch copies a session from
   F1 into the source archive in R2, as a new snapshot each time (rule 6). Build reads that archive, Jolpica and
   FastF1's schedule file, and nothing from F1. Only fetch needs a network F1
   answers (AR-13); build was run with F1 blocked (AR-11, command 20). A
   change to an analysis or to the format is then a rebuild on any machine.

   Anything else a build needs from a host that might refuse cloud addresses,
   such as the circuit information in AR-17, is fetched and archived with the
   session. The archive sits under a prefix the Worker does not serve; its
   public paths are an allowlist (`worker/src/index.mjs:190-192`).

5. **Identity survives a calendar change (AR-20).** Published sessions are
   keyed by F1's session key. The schedule is fetched on every run and
   published as data. Pages look up year, round and names in the index at
   runtime.

6. **Completeness is checked before a session counts as done (AR-21).** Fetch
   measures coverage and records it in the snapshot: per driver, the share of
   laps with car data and, separately, the share with position data, and
   whether weather, race control and track status arrived. Each has its own
   bar.

   Track status is checked as a feed that arrived, not lap by lap. FastF1
   accepts an empty track-status feed and then marks every lap inaccurate
   (`fastf1/core.py:1996-2007, 2286-2294`), and `clean_laps` drops inaccurate
   laps (`backend/app/analysis/common.py:32-33`), so race pace and every
   analysis built on clean laps would come out empty with all timing laps
   present.

   The shares are taken against the laps a driver is expected to have, not
   the laps that loaded, and timing has a bar of its own. For a race or
   sprint, the expected count is the driver's completed laps in the Jolpica
   classification, and every classified driver has to appear in the timing
   with that many laps, within a stated tolerance for retirements, drivers
   who did not start and laps FastF1 generates. For other sessions, which
   have no lap count to compare with, every driver in the result has to have
   timing laps and the session-status feed has to show the session ended.
   Without this, a timing feed cut short would report full coverage of the
   few laps it kept.

   Tyre data has a bar per driver: the share of laps with a compound, a tyre
   age and a stint. When a driver's `TimingAppData` is missing, FastF1 keeps
   the timing laps and fills in an empty compound, no tyre age and a single
   stint (`fastf1/core.py:1532-1539`). The stints, the strategy tab and tyre
   degradation are then wrong or empty while every other figure is unchanged.

   The bars are not a list of the feeds that have failed so far. FastF1 3.8.3
   requests eleven feeds from F1 when it loads a session: session info,
   driver list, timing data, timing app data, track status, lap count,
   session status, weather, race control, car data and position data
   (`fastf1/core.py`, the `api.` calls in `Session.load`). Step 3 gives each
   of them a bar, or a written reason it needs none, and repeats that for
   every feed added later (`PitStopSeries`, AR-16; circuit information,
   AR-17). The bars are tested on a recorded race by removing one feed at a
   time, for the session and for a single driver: each removal has to leave
   the session incomplete, or the build output has to be shown unchanged.

   A lap counts toward a feed's share only if its data is usable, judged on
   the samples as fetched, before any interpolation or thinning: the samples
   run from the start of the lap to its end, no gap between two of them
   exceeds a stated maximum, and the feed's channels are present (speed,
   throttle, brake, gear and RPM for car data; X and Y for position). One
   sample per lap would otherwise count as full coverage while track
   dominance and the replay came out empty. Step 3 sets the span and gap
   limits from a recorded race and tests them on that race with its telemetry
   thinned inside each lap. Snapshot selection and criterion 1 use these
   figures. A session
   below any bar is fetched again on later runs, and published as partial,
   naming the feed that is short, only after a retry window.

   A retry starts from an empty FastF1 cache directory. FastF1 reuses a
   cached response for as long as its cache version matches
   (`fastf1/req.py:432-435, 489-496`), and the loader always enables the
   cache (`fastf1_service.py:29`), so a retry over the same directory returns
   the same incomplete data without asking F1. Each fetch is stored as a new
   snapshot under its own name; nothing is overwritten. Build selects one snapshot
   for each session by a fixed order, so a retry that does worse changes
   nothing. A snapshot that meets every bar ranks above one that does not.
   Among snapshots that fall short, the one that meets more bars ranks
   higher, then the one whose weakest figure (the lowest share for any driver
   on any feed) is higher. Only then does the later fetch win. A retry can
   improve one feed and lose ground on another; this order decides that case,
   and it is tested with one.

7. **The format version is part of the path.** Artifacts are published under a
   version prefix. The frontend reads the one version it was built for and
   checks `schema_version` in the manifest of the generation it pinned, since
   most artifacts carry no version of their own (AR-09). Today data and pages are built together
   and cannot disagree; once pages load at runtime they deploy separately. A
   format change is published under a new prefix before the frontend that
   reads it is deployed, and the old prefix stays until then.

### Order of work

1. **Secure the source and settle where fetching runs (AR-11, AR-13).** Copy
   the local FastF1 cache to R2, compressed; it is the only copy of the source
   for all 33 sessions. Then ingest one completed session on a GitHub-hosted
   runner with an empty cache, with the assertions in AR-13. Expect a refusal,
   and plan for fetching on a self-hosted runner or a local scheduled task.
2. **One session, end to end, on the real infrastructure.** Take one race that
   is already fetched. Archive it, build it from the archive, publish it to R2
   through the S3 API under a generation prefix with a conditional pointer
   write, serve it from the Worker, and load one tab from it at runtime on the
   deployed site. Follow rules 1 to 4 and 7 from the start. The artifact
   contents can stay in today's format. Nothing is widened until this works
   against the real bucket, Worker and site.
3. **New artifact format and typed contract (AR-05, AR-09).** Columnar
   telemetry bundled per driver, minified JSON, integer milliseconds, Pydantic
   models at the write boundary, generated TypeScript types. Add both pit-stop
   durations (AR-16) and the official corner positions (AR-17), omit DRS from
   2026 (AR-18), key sessions by F1's session key (AR-20) and record coverage
   (AR-21). Run the analyses on the full telemetry and choose the published
   resolution separately; today both are cut to 300 samples per lap (AR-11).
4. **The batch command (AR-06, AR-10, AR-15).** Fetch and build as two stages
   of one command, idempotent against R2 under rules 2 to 6. Move the Python
   code into one package. Ingest sprints, take standings from Jolpica and
   re-fetch recent classifications on every run. Run it over the backlog first
   (2026 rounds 10 to 16), then on a schedule for each remaining weekend.
5. **Every page loads at runtime (AR-07, AR-02).** All eleven build-time
   readers, with session routes resolved at runtime. Remove real session data
   from git and from the deploy, and keep the sample dataset in the published
   layout for local development. The build then reads no published data.
6. **Remove the old path (AR-03, AR-04, AR-06, AR-10, AR-14).** The queue, the
   D1 job tables, the dispatch, the callbacks, the scheduler module,
   `local_queue_worker.py`, the four workflows and the FastAPI shell. Do this
   once the criteria below hold, not before.
7. **Product quality (AR-08, AR-12).** Runs alongside steps 2 to 6. The chart
   fixes and the method fixes that need no new data can start at once,
   the pit-loss estimate among them (AR-16); the corner fix and the display
   of the two pit-stop durations follow step 3. Decide the scope of the
   placeholder pages.

The new path is built beside the old one. The old path receives no further
fixes and is deleted in step 6. Step 2 comes early because the old publisher
was written and tested against fakes and has never completed a real run
(AR-01, AR-04). From step 2 on, each step ends with a real publication, not
only with passing tests.

### Done when

The rewrite is finished when all four hold. The thresholds were settled in
decision 6.

1. **Unattended.** Every in-scope session (decision 5) of three consecutive
   race weekends is on the site and complete, meeting every bar in rule 6,
   within 48 hours of finishing if fetching runs on a local machine and
   within 24 hours otherwise, with no manual step. A partial publication
   does not count. The one exception is a feed F1's archive itself does not
   hold for that session, shown by a fetch from a network F1 answers and
   listed by name with the result. Seven weekends remain in 2026, from Singapore on 2026-10-11 to Abu
   Dhabi on 2026-12-06. To be measured this season, the scheduled job has to
   be running by Las Vegas on 2026-11-21; otherwise the next chance is 2027.
2. **No deploy for data.** A newly published session, a corrected
   classification and a standings update each appear without a frontend build.
   The standings case includes a correction that does not advance the round.
3. **Rebuildable anywhere.** Every published session has been rebuilt from the
   R2 archive on a machine that has never fetched from F1.
4. **Safe with two publishers.** Two runs started together against the real
   bucket leave every session from both in the index. A run from an older
   pipeline version, started so that it loses the pointer write to a newer
   one, leaves the newer generation in place. A test that forces one
   publisher's pointer and index writes between another's pointer listing
   and index write leaves both sessions in the index.

### Size

About 4,050 lines are removed outright: the scheduler, four workflows, the
Worker's repository and session-status modules with their tests, the
migrations, the API-only backend code and the ingestion panel. A further 3,900
lines (`local_queue_worker.py`, its tests and `worker/src/index.mjs`) are
replaced by much smaller code. That is roughly 7,000 of 18,500 tracked source
lines. This is an estimate from file sizes, not a plan-level count. It does
not count what the publication rules add: the archive stage, a
conditional-write helper and the pointer reader in the frontend.

---

## 7. Pull requests and issues

The repository has no GitHub issues, open or closed. At the time of the review
there were four open pull requests, all opened on 2026-07-27 and all on the
cloud ingestion path.

| PR | Content | Relation to this plan | Status |
| --- | --- | --- | --- |
| #7 (draft, conflicting) | Reference-only branch from 2026-07-13: generation-prefixed publishing, an R2-only source, and a runtime-fetching frontend shell | Its frontend shell and R2-only source were recorded as "deliberately not being taken". This plan takes them (steps 2 and 5), so the branch is prior art for the rewrite. Its `/seasons/explore` page and client loaders are the starting point for runtime routes (AR-07). | Open, kept as reference |
| #8 | Guard against a stale status poll in `SessionIngestionPanel`; adds a frontend test runner to CI | The panel is removed if browser-requested ingestion is dropped. The test runner and the request guard are independent of the plan and worth keeping. | Open |
| #9 | Immutable generations with a pointer flip; deletes about 450 lines of rollback code | The pointer and generation layout are adopted. The Worker key resolver and the keep-one-previous retention are not (section 6, rule 1). The publisher half is still built on `wrangler` and the callback contract, both of which the rewrite replaces. Its description records that its first commit shipped a data-loss bug in generation pruning. | Closed 2026-10-05 as superseded |
| #10 (stacked on #9) | Seeds D1 session status from R2; publisher and Worker contract fixture; pins newlines in `write_json` | The D1 seeding is removed with the old path (step 6). The contract fixture and the newline fix should be carried over. | Closed 2026-10-05 as superseded |

The branches of #9 and #10 (`feat/immutable-artifact-generations`,
`feat/session-status-r2-seed`) were left in place. From them the rewrite should
carry over:

- The pointer validation in `loadActivePointer`
  (`worker/src/artifact-store.mjs`) and its distinction between an absent and
  an unreadable pointer, moved to the frontend's pointer reader.
  `createR2KeyResolver` itself is not carried over (section 6, rule 1).
- The `active.json` pointer and generation layout. The pruning guards are kept
  for when pruning is built, with retention by period instead of by count.
- `docs/r2-generation-validation.md` as the starting point of the checklist
  for the first real publish, and the publisher and Worker contract test with
  its committed fixture. Both are rewritten before step 2, because as they
  stand a correct implementation of rule 1 fails them. The checklist expects
  the Worker to resolve a conventional path through the pointer (its part 2)
  and a third publication to prune (its part 4), and the contract test
  expects the same resolution (`worker/tests/generation-contract.test.mjs`
  on `feat/session-status-r2-seed`). The rewritten versions read the pointer
  in the frontend, request generation paths, check that a view pinned to one
  generation still reads it after a later publication, and leave pruning out
  until retention by period exists.
- The `newline="\n"` pin in `write_json` and the `.gitattributes` rule.

---

## 8. Decisions needed

1. **Browser-requested ingestion.** Step 6 removes it. It works only behind
   Cloudflare Access, and a scheduled job that ingests every completed session
   makes it unnecessary. If it is wanted, a thin Worker endpoint that triggers
   the workflow directly would serve, without the queue or D1.
   **Decided 2026-10-05: dropped.**
2. **Where fetching runs.** If step 1 confirms the refusal, the choice is
   between a self-hosted GitHub runner, which keeps the workflow interface, and
   a scheduled task on a local machine, which is simpler. Only the fetch stage
   is tied to that machine; building and publishing can run on hosted runners.
   The machine does not have to be on when a session finishes, because the job
   catches up on its next run and F1's archive keeps past sessions. It does
   have to run within the window set in decision 6.
   **Decided 2026-10-05: a scheduled task on a local machine, if step 1
   confirms the refusal.**
3. **PR #8.** Its fate follows from decision 1. If the ingestion panel goes,
   salvage the test runner and the request guard and close the rest; if it
   stays, merge it.
   **Decided 2026-10-05: salvage the test runner and the request guard into a
   new pull request and close #8.**
4. **Scope of live timing and the placeholder pages.** `/live` and `/settings`
   are stubs today; either build them or remove them from the navigation. Live
   timing needs a paid OpenF1 account (AR-19).
   **Decided 2026-10-05: remove both from the navigation, and remove the live
   routes in step 6. Revisit live timing after the rewrite.**
5. **Which session types to ingest.** A meeting has five sessions. Standings
   come from Jolpica under this plan, so no session type is needed for them.
   The analyses are race-oriented, and the qualifying-delta analysis is not
   part of the published artifacts (AR-10, AR-12). Recommended: races
   and sprints first, and qualifying and practice once they have a view of
   their own. The answer sets the size of the archive and the scope of the
   first criterion in section 6.
   **Decided 2026-10-05: races and sprints.**
6. **The acceptance bar.** Section 6 proposes 24 hours and three consecutive
   weekends. Settle both before step 4, since they decide how often the fetch
   machine has to run.
   **Decided 2026-10-05: 48 hours if fetching runs on a local machine
   (decision 2), 24 hours if it runs on a hosted runner. Three consecutive
   weekends stands.**

---

## 9. Review of the plan

After the first version of this document was committed, the plan in sections 6
to 8 was reviewed twice on 2026-10-05: by Claude Opus 5.5, and independently
by GPT-6.1 Sol. The two reviews agreed on two points and otherwise raised
different ones. Each point was checked against the code, the run history or a
reproduction before the plan was changed. Neither review changed any other
file, and neither ran a live ingestion or publication.

| # | Point | Raised by | How it was checked | Result |
| --- | --- | --- | --- | --- |
| 1 | PR #9's read path resolves the pointer for each request, so one page can mix generations; readers of a superseded generation need a retention rule | Both | Reproduced (command 22); retention read in PR #9's publisher | Confirmed. Section 6, rule 1; AR-04; section 7 |
| 2 | Removing the queue removes the only serialisation of publishers, and the index merge can then lose a session | GPT-6.1 Sol | Merge path and workflow concurrency read; R2 documentation (command 23) | Confirmed. Rule 2; AR-06. Of the two remedies offered, conditional writes were chosen over a single enforced writer |
| 3 | Step 5 covered the session tabs only; other pages read data at build time | GPT-6.1 Sol | Eleven imports of `lib/api-server.ts` | Confirmed. AR-07; step 5; criterion 2 |
| 4 | A request for `Index.json` does not test ingestion, and the loader tolerates missing telemetry | Both | `fastf1_service.py` read; executed (command 21) | Confirmed, and wider than raised: such a session is also reported complete. AR-13; AR-21; rule 6 |
| 5 | The first real end-to-end run came last, as it did for the path being replaced | Claude | AR-01, AR-04 | Order of work, step 2 |
| 6 | Sessions are keyed by round number, and the calendar has changed | Claude | Command 18 | AR-20; rule 5 |
| 7 | "Not yet published" was undefined, and the catalog is built from local files | Claude | `backfill.py:88`, `artifacts.py:73-105` | Rule 3 |
| 8 | The normalised dataset is the wrong thing to archive, and fetching should be separate from building | Claude | Commands 19 and 20 | AR-11; rule 4; step 1 |
| 9 | Runtime loading lets data and frontend disagree about the format | Claude | AR-09; no version check exists | Rule 7 |
| 10 | Product-quality work was called independent, but two analysis fixes need the new fields | Claude | AR-08, AR-16, AR-17 | AR-08; step 7 |
| 11 | No acceptance criteria, and no decision on session types | Claude | Sections 6 and 8 as first written | "Done when"; decisions 5 and 6 |
| 12 | The refusal by F1 was better evidenced than stated, and Jolpica was unaffected | Claude | Command 16 | AR-13 |
| 13 | Stale statements: PRs #9 and #10 described as open, 22 meetings, a machine "on when sessions finish" | Claude | `gh pr list`; command 18 | Section 2; AR-02; AR-04; decision 2 |
| 14 | AR-01 put both 2026-07-25 ingestion failures down to FastF1; one was a command-line flag error | Claude | Command 16 | AR-01 |

The revised plan was then sent back to GPT-6.1 Sol through Codex, read-only,
and revised until a review raised nothing at its two higher priorities. The
points from those rounds:

| # | Point | Round | How it was checked | Result |
| --- | --- | --- | --- | --- |
| 15 | "Read again and retry" lets a publisher that lost a conditional write put its older build over a newer one, and criterion 4 would not notice | 1 | Followed from rule 2 as written; Sol reproduced the sequence in memory | Confirmed. Rule 2; criterion 4 |
| 16 | A better archive after a retry triggered no rebuild, so a partial session stayed partial | 1 | Rule 3's three conditions as written | Confirmed. Rule 3 |
| 17 | A retry through the current loader refetches nothing, because FastF1 reuses its cache | 1 | `fastf1_service.py:29`, `fastf1_ingestor.py:28`, `fastf1/req.py:432-435, 489-496` read | Confirmed. Rule 6; AR-21 |
| 18 | The share of laps with telemetry does not show that position data arrived | 1 | `normalizer.py:512-528`, `position_replay.py:15-20` read | Confirmed. Rule 6; AR-21; AR-13 |
| 19 | Pit-lane time with safety-car stops removed is still not pit loss | 1 | `strategy.py:15-16` read | Confirmed. AR-16; AR-08; step 7 |
| 20 | Coverage measured over the laps that loaded passes a race whose timing was cut short | 2 | `fastf1_service.py:96-102`, `result_validation.py:10-40` read; Sol truncated `2026-08-r` to 22 laps in memory and both validators passed | Confirmed. Rule 6; AR-21 |
| 21 | Every acceptance criterion could pass with all sessions published as partial | 3 | "Done when" as written | Confirmed. Criterion 1 |
| 22 | "Best coverage" gave no order for snapshots that differ feed by feed | 3 | Rule 6 as written | Confirmed. Rule 6 |
| 23 | A lap with one telemetry sample counted as covered | 4 | `advanced.py:484`, `position_replay.py:24` read; Sol thinned `2026-08-r` to one sample per lap in memory and every lap still counted | Confirmed. Rule 6 |
| 24 | A conditional index write protects nothing if the pointers are listed before the index is read | 4 | Rule 2 as written; Sol reproduced the interleaving in memory | Confirmed. Rule 2; criterion 4 |
| 25 | Completeness did not cover track status, without which no lap counts as clean | 5 | `common.py:32-33`, `normalizer.py:293-296` read; Sol removed the feed from `2026-08-r` in memory and clean laps fell from 1,149 to none | Confirmed. Rule 6 |
| 26 | "Keep the later round" left a same-round standings correction unpublished | 5 | Rule 2 as written | Confirmed. Rule 2; criterion 2 |
| 27 | The checklist and contract test carried over from PRs #9 and #10 test the Worker resolver and pruning that rule 1 rejects | 5 | Both files read on their branches | Confirmed. Section 7 |
| 28 | Completeness did not cover tyre data; a driver without `TimingAppData` keeps all timing laps and loses compounds, tyre age and stints | 6 | `fastf1/core.py:1532-1539` read; Sol removed one driver's feed from the cached Austrian race in memory | Confirmed. Rule 6, which now requires a bar or a reason for every feed FastF1 requests, tested by removing each in turn |
| 29 | `schema_version` is not in every artifact, only in the catalog, indexes and manifests | 7 | `pipeline/artifacts.py` read | Confirmed (minor). AR-09; rule 7 |

Round 7 raised only point 29 and passed the plan. Point 29 was applied after
that verdict and has not been reviewed.

---

## 10. Implementation progress

Work on section 6 started on 2026-10-05 on the branch `rewrite/data-plane`
(pull request #11). This section records what each step has verified on the
real infrastructure. It is updated as steps finish; the plan above is not
rewritten.

### Status by step

| Step | Status | What exists |
| --- | --- | --- |
| 1. Secure the source, settle where fetching runs | Done, but for the schedule | The probe ran and settled AR-13. The 21 races and sprints of 2026 and the 30 of 2025 were fetched afresh from F1 and are in the R2 archive, so the old FastF1 cache on one machine is no longer the only source of anything; `python -m f1data archive-directory` copies it if a second copy is wanted. Fetching runs by hand on one machine until the scheduled task exists (step 4) |
| 2. One session end to end | Done | Fetch, archive, build on a hosted runner, publish, Worker, and `/session` loading a tab at a time |
| 3. New artifact format and typed contract | Done | Format 2, published under `v2/`: one model per artifact (`f1data/models.py`), exported as `schema/published-v2.schema.json`, from which the site's types are generated (`npm run types`; a test fails when they drift). Telemetry per driver as arrays, whole milliseconds, both pit-stop durations, official corners, coverage, analyses on full telemetry. `f1data/legacy.py` and the site's format-1 reader are gone. Published for 43 of the 51 archived sessions; the other eight are short of a bar and inside their retry window |
| 4. The batch command | Done, but not scheduled | `run` is the whole job: `build`, `fetch-due` (through a spool that keeps a session F1 served until the archive has it), and `build` again for what was fetched. It writes down when it ended, and `last-run` says when that is too long ago. The scheduled-task recipe is in `docs/data-plane.md`. Nothing has registered it: it needs R2 credentials on the machine that fetches |
| 5. Every page loads at runtime | Done | Every page loads its data in the browser from `v2/`, sessions are addressed by F1's key, and nothing is read at build time. `frontend/public/data` (1.2 GB, 10,935 files) is out of the tree; for work offline `python -m tests.sample_bucket` writes and serves a made-up race in the published layout. The old build-time dashboard code is removed |
| 6. Remove the old path | Not started | |
| 7. Product quality | Partly done | Six analysis methods fixed (AR-08, AR-16). `/live` and `/settings` removed, chart fixes, dead code removed (AR-12) |

### What was verified

| # | Check | Result |
| --- | --- | --- |
| 1 | `python -m f1data probe` for the 2026 Austrian GP race on `ubuntu-latest`, empty cache (runs 37390032860 and 37390272298) | `livetiming.formula1.com` answered 403 to all 30 requests, with `server: CloudFront` and `x-cache: Error from cloudfront`. FastF1's mirror answered 404 to all 30. Jolpica and the schedule file answered 200 |
| 2 | The same probe from a residential network | 11 feeds, all 200. 1,339 laps; car and position data for 22 of 22 drivers |
| 3 | `tests/test_store.py` against the real bucket through R2's S3 API, with the repository's Cloudflare token (run 37391255736 and later) | All cases pass. Of six writers racing on one version with `If-Match`, and six with `If-None-Match: *`, exactly one wins each time |
| 4 | Build of the 2026 Austrian GP race on a hosted runner from the R2 archive (run 37392847582) | Built and published without a request to F1. Requests to F1's hosts are refused during a build, so this holds by construction |
| 5 | The published session through the new Worker | Pointer and index answer 200 with a 30-second cache life, generation paths 200 and immutable, the archive 404 |
| 6 | `/session?year=2026&round=8&session=R` in headless Edge against the real Worker | Five requests on load (index, pointer, manifest, results, drivers). The lap-times artifact is requested only when its tab is opened |
| 6a | The same page on the Pages preview of the branch, in headless Edge | Rendered the session header, "Complete data" and the 22-row classification, loaded at runtime from the Worker |
| 6b | Nine pages of the Pages preview built from `d864341`, in headless Edge against the real Worker: home, season, meeting, session by key, session opened on its results tab, standings, strategy, drivers, circuits | Each rendered its data, loaded in the browser. The session page showed the Austrian GP result with its ten tabs and the picker on that session; the standings showed the table after round 16; the old build-time routes answer 404 |
| 6c | The 2026 Austrian GP race built twice from the same snapshot, once with FastF1 fetching the result and the first-lap times from Jolpica during the load, once with both gathered beforehand and every request refused during the build | The same generation, `0e8945dc1038`: byte for byte the same artifacts |
| 7 | F1's session key for the 21 races and sprints of 2026 | Present for all 21 |
| 8 | The same snapshot built on Windows and on Linux | Different generations: 1,324 of 1,342 files differ, by float noise of about 1e-12 in telemetry distance and position. Rounding in the new format (step 3) should remove it |
| 9 | Format 2: five sessions (11315, 11240, 11299, 11731, 11342) each built twice on Windows, in separate processes with different hash seeds | The same generation both times, for all five. Not yet built on Linux; `tests/fixtures/golden-11315.json` holds the checksum of every file of the Austrian race, so running `tests/test_recorded_race.py` there is the check |
| 10 | Format 2: every lap's telemetry of the Austrian race against FastF1's per-lap call | 1,339 laps, 757,210 samples, nine channels: no value differs. The build takes 2.6 s for what took FastF1 about six minutes, which went on a car-ahead channel nothing uses |
| 11 | Format 2: the Austrian race built from the archive | 9 s to build, against 369 s. 44 objects and 21.5 MB, against 1,343 and 108.5 MB. The manifest is 5.9 kB against 177 kB |
| 12 | Format 2: each of the eleven feeds and both extras removed from the recorded Austrian race, whole and where it applies for one driver | Every removal leaves the session incomplete but one: a single driver's stops missing from F1's pit-stop feed |
| 13 | Format 2 built and published by the hosted workflow from the R2 archive, four sessions at a time (run 37533733208, about four minutes) | 43 of 51 sessions published: 26 of 2025 and 17 of 2026. Eight held, short of a bar, until their retry windows close on 2026-10-08. The generations built on Linux are the ones built on Windows from the same snapshots (11315 `fa9452ba60c8`, 11240 `66dab6df3784`), which check 8 found was not so for format 1 |
| 14 | Every archived session loaded and measured again with the code of pipeline version 7, on the machine that holds the archive (51 sessions) | FastF1 had added rows to the car data of five sessions, 4,488 of them in the 2026 Spanish GP. All fall before the start of the race, so no published lap held one. One lap is no longer published: Bortoleto's last of the 2025 São Paulo sprint, whose car data stops 6.7 s before the lap is timed as ending and which the coverage never counted. The 2026 Australian GP has F1's stationary time for 28 stops where it had 8 |
| 15 | The recorded Austrian race built, not only measured, with each of its eleven feeds taken out in turn, with one driver taken out of F1's driver list, and with one driver left in it without a code | Seven of the eleven still build and say what they lack; the four FastF1 needs together to make laps fail with that reason. Both driver-list cases build under the classification's code. All 51 sessions measured again with pipeline version 8's code: no figure differs from its record |

### What real data changed

- **The deployed Worker answers every plain GET with 206.** R2 reports the
  range it returned on every read, the whole object included, and the Worker
  turned any reported range into `206 Partial Content`. The new Worker answers
  206 only to a request that asked for a range. The old Worker is unchanged.
- **FastF1 fills in for a car that is missing from the car feed.** It gives
  the car a row for every moment another car has one, with zeros in every
  channel, and a loaded session marks such a row only by the text `nan` where
  the feed's name should be. A fix that looked for an empty mark passed every
  test written for it and did nothing on a real session; loading the 2026
  Belgian GP from the archive showed it.
- **F1 reported twenty of one race's pit stops with no lap.** In the 2026
  Australian GP twenty of twenty-eight reports came up to 66 seconds late and
  said no lap. They were matched by driver and lap, so they were dropped, and
  nothing noticed: the bar asks only that the feed vouches for some stop. In
  the other fifty sessions every report names its lap.
- **F1 sends some pit stops twice, and a zero for a sensor that is off.** In
  the 2025 Canadian GP 29 stops arrive under two places of their driver's
  list, a tenth of a second apart; seven archived sessions have at least one
  such pair. The stops were published once each, and the count beside them
  was of places: 62 for 33. And the track temperature of the 2026 Azerbaijan
  and Bahrain GPs reads 0.0 in two samples each, between readings of 47 and
  of 34 degrees: the frontend drew the spikes and the summary said "track
  0.0-48.1C". Both were in the feeds as F1 sent them, and neither was found
  by reading code.
- **A session can be measured correctly and still not build.** With F1's
  driver list taken out of the Austrian race's archive, FastF1 loads all
  1,339 laps and every car's data, and writes an empty driver code on each
  lap. The measurement was right (a driver-list shortfall for everyone); the
  build read the laps by that code, skipped them all and failed, on every
  run, where the session should have been published as partial. Where the
  list has a driver without a code, FastF1 writes the word `None`. The
  recorded race is now built with each feed removed, not only measured, and
  a driver is found by car number.
- **FastF1 can make no laps without four feeds together.** With the timing,
  the tyre data, the track status or the session status missing it makes
  none, and such a session cannot be built from what FastF1 loads. It fails
  with that reason.
- **Timing needs no tolerance** (rule 6 allowed for one). Across the 462
  driver entries of the 21 sessions, timing had the classified laps 452 times
  and one lap more 10 times. It never had fewer. A tolerance of one lap would
  have let a driver classified with one lap pass every bar with no data.
- **Tyre age cannot be a bar.** F1 does not report the age of a set that went
  on used. In the 2026 Barcelona race that is 21 of one driver's 60 laps, and
  in the race at Sepang 152 laps across eleven drivers. The tyre bar is
  compound and stint; tyre age is counted beside it.
- **Four of the 21 sessions fall short of a bar at the source.** Monaco: F1's
  position feed stops in lap 5 of 78, for every driver. Hungary: no compound
  for 25 of one driver's laps. Spain and Sepang: MultiViewer has no corner
  positions for the two new circuits. The old pipeline would have reported all
  four complete (AR-21).
- **The pit-stop feed is not held for every season.** F1 answers 200 for
  `PitStopSeries` in 2026, 2025 and from the 2024 United States GP, and 403
  before that.
- **Jolpica's burst limit is easy to reach.** Asking for the classification of
  21 sessions in a row earned a 429 on the next request. The job now asks only
  for sessions of the last 30 days, and waits and asks again on a failure.
- **F1's pit-stop feed leaves whole drivers out.** In the Austrian race it has
  36 of the timing's 44 pit-lane entries, and nothing at all for three
  drivers. A stop it does not cover is published with the timing's figure and
  `stationary_ms` null. No bar can ask for every driver's stops, so one
  driver's stops going missing is the one removal no bar notices (rule 6).
- **F1 sends (0, 0) for a car it has no position for, on track as well as in
  the garage.** At Monaco it did so for the cars on the grid until up to 4.7 s
  into the race, and FastF1 merges those samples as positions. Format 2 leaves
  them out, never extrapolates a position past the last real sample, and
  publishes null where there is none.
- **The inferred corner analysis found eleven corners at a circuit with ten.**
  Five of the eleven in the Austrian race were one driver each: Bottas, whose
  only complete lap was the first, with a distance axis 200 m out of step. By
  the official corner positions every driver's figures sit under the right
  corner.
- **Two of five sessions have feeds that repeat themselves, and no bar sees
  it.** F1's car and position feeds send a sample about four times a second.
  In the Hungarian race the car feed from lap 7 and the position feed from
  lap 15 send the sample before again most of the time, for nearly every car,
  to the flag: at the median lap six car samples in ten and nine position
  samples in ten are repeats, and more than a quarter are on 1,169 and 998 of
  the 1,279 clean laps. In the Chinese sprint it is the car feed, on 163 of
  296 clean laps. The samples arrive on time, so the bars on car and position
  data pass. The telemetry of such a lap is wrong: the speed stands still, so
  the lap measures anywhere from 1,745 to 5,214 m at the Hungaroring and
  4,352 to 6,459 m in Shanghai, and the car stands still on the map and then
  jumps, 347 m on Hungary's fastest lap. FastF1's own telemetry is the same,
  sample for sample, on the five such laps compared. The Austrian and Sepang
  races have none of it, nor has Monaco's car feed. Left alone: a bar for it,
  which is a publication rule, and which lap the analyses read (below).
- **Corners are checked against, and placed on, a lap whose position data is
  whole.** Measured against Hungary's fastest lap the 16 corners looked 44 m
  off the track at the median and up to 116 m, and FastF1, which places
  corners along the fastest lap, had put two pairs of them at one point of it.
  The map is right: the corners are within a metre of the line of each of
  the 40 laps of that race with the most complete position data, at the
  median lap, and within 5 m at the worst. The reference lap is now the
  fastest clean lap whose position samples are never more than 150 m apart,
  which all but one of the 2,260 clean laps of the other four sessions are,
  and archived distances that do not go round the lap in the order of the
  corners are measured again on it. Of the 49 circuit files archived for 2025
  and 2026, Hungary's is the one whose distances do not, and Monaco's the one
  with none. `corners.json` still says whether the corners lie on the
  reference lap's line (`fits_track`), for a map of another layout and for a
  session with no whole lap. No session fails it.
- **Monaco is the one race whose corners the build has to place for want of
  distances.** FastF1 places a circuit's corners along the session's fastest
  lap, which at Monaco has no position data, so the 19 corners are archived
  without distances. The build places them on the fastest lap that has
  position data (lap 5), all within 15 m of its samples, and the other 21
  cars' laps are read by distance: the hairpin at a median of 43 kph, the
  tunnel at 252.
- **A lap that stops short was read as going everywhere.** Verstappen's only
  lap of that race ends at the chicane, 2,107 m into a lap of 3,278 m, and he
  had figures for all 19 corners: the nearest of his samples to each one he
  never reached was taken for it. For Tabac and the swimming pool those are
  within 50 m, on the road out of Sainte Devote and on the grid. A sample is
  now a corner only if it is within 50 m of it, and on a lap that was not
  timed all the way round it must also be within 200 m of where a normal lap
  has the corner. He has figures for the eleven corners he drove through.
- **A lap's distance can be far out.** In the Chinese sprint eight drivers'
  fastest laps are among those whose car feed repeats itself, for many
  seconds at a time, and measure the 5.4 km lap from 8% short to 15% long.
  Looking for a corner only near where the lap's distance put it found the
  edge of the search, hundreds of metres from the corner. A lap that was
  timed all the way round passed every corner, so a sample at a corner is now
  taken for it wherever the lap's distance says it is. What is left alone:
  the corner analysis and the car performance take each driver's fastest lap
  whatever the state of its telemetry, so in that sprint they report braking
  that lasts up to 25 seconds, and in the Hungarian race a slowest speed
  through turn 1 of anything from 80 to 335 kph. Track dominance already
  takes the fastest lap whose telemetry is the length of a lap (AR-08). The
  same choice here, with a test for a feed that repeats itself, would put it
  right.
- **The old format's numbers were off in two more places.** 152 sector times
  of the Austrian race were a millisecond low, cut off instead of rounded.
  Wind speed was published as `wind_speed_kph` in metres a second.
- **The order on track is the classification.** Taken from the timing alone
  (most laps, then who took the flag first), the Austrian race comes out as
  Jolpica's result for all 22 places, laps and gaps, to the millisecond. That
  is what a session is published with, marked provisional, when Jolpica has no
  result.

### Reviews of the code

| Round | Reviewer | Commit | Result |
| --- | --- | --- | --- |
| 1 | GPT-6.1 Sol, through Codex, read-only | `c8bd3c2` | Twelve findings, two of which could publish wrong data or lose source data: a publisher holding a stale calendar could attach another race's result to a session, and two directory copies in one second could share a key. All twelve are fixed in `d58794f`, each with a test that fails without the fix |
| 2 | The same | `723aef5` | Thirteen findings, one of which published wrong data: a build made under the old calendar could be published after the calendar changed. Fixed in `9d857fb`; `tests/test_second_review.py` reproduces each |
| 3 | The same | `9d857fb` | Seven findings, three of which could publish wrong data. A change to the calendar alone left the old build in place, because the pointer did not record the calendar entry. A driver left out of today's classification kept the result the archive had for them. A publisher that had read the calendar earlier in its run could put the old calendar's index over a newer one without a conflict. The other four: a session published short after a late correction, or short where its record said whole, was never fetched again; a feed that arrived unfinished was taken for one F1 does not hold; a pit-stop duration of `1e308` stopped a fetch. Fixed in the commit that adds `tests/test_third_review.py`, which reproduces each; seventeen of the fixes were removed one at a time to check that a test fails without them |
| 4 | The same | `0651e58` | Four findings, one of which could publish wrong data: the build asked FastF1 for the session by year and round, which read the calendar a second time and, after a change, came back with another race's event around this race's feeds. The fix goes further than the finding. A build is now made from the calendar row that was gathered, with every network request refused, and the two things FastF1 fetched from Jolpica on the way (the result, and the first-lap times of a race) are gathered beforehand and are in the pointer's fingerprint. The other three: a snapshot whose record flattered it could keep a whole one from ever being published, so a record that disagrees with its feeds is now corrected in the archive before anything is decided from it; a feed absent for every driver was fetched for ever because its shortfalls are counted by driver; a pit-stop duration of `10**400` stopped a fetch. `tests/test_fourth_review.py` reproduces each, and thirty-two fixes of rounds 3 and 4 were removed one at a time |
| 5 | The same | `d864341` | Two findings, both in what round 4 added. Wrong data: the result and the first-lap times are two requests by round, and if Jolpica renumbered between them the times of another race were joined to this one's result; they are now used together only when both answers name the same race. And a correction of a record was trusted too far: FastF1 loads no feed when the calendar row's `F1ApiSupport` flag is unset, so a build through such a row would have recorded a full snapshot as empty, over a correct correction, and nothing looked again once a session was published. A build now loads the feeds whatever the row says, writes a correction only against the one it read, leaves a newer pipeline version's alone, and the pointer records the figures it was judged by so that a later correction is measured again. `tests/test_fifth_review.py`; forty-five fixes of rounds 3 to 5 removed one at a time |
| 6 | The same | `00a1d28` | Nothing that could publish wrong data. One finding: `copy-archive` copied a correction of a snapshot's record like any other object, so a spool could put an old correction over one a newer pipeline version had written in the bucket. Corrections are no longer copied between stores; the destination's own build measures the snapshot. `tests/test_sixth_review.py` |
| 7 | The same, asked to look across everything once more | `0d51442` | Nothing that could publish wrong data, and the round-six fix closed. Two findings in code no earlier round had dwelt on. A batch of fetches stopped after two failures in a row whatever their cause, and since a failed fetch archives nothing the same two sessions were first in line on every run: two sessions F1 does not hold would have kept every later one from being fetched. The batch now asks whether F1's archive answers at all before it stops. And the directory store's conditional writes held only within one instance of it; they now take a lock on a file in the directory, so two runs sharing one behave as two publishers sharing the bucket. `tests/test_seventh_review.py` |
| 8 | The same, asked this time to follow everything that is read back or parsed, every clock, and every failure that is caught | `042c5cb` | Eight findings, one of which could publish wrong data given a misplaced object in the archive: a snapshot's marker was believed about which session it belonged to, so one filed under another session's key was built and published under that session's pointer. Markers are now checked against their key, and a snapshot is never published to a pointer that is not its session's. The rest: the question "is F1 answering" was asked of the season that had failed; a session whose calendar start had been corrected by more than twelve hours could not be built even from a fetch made since; a result with no lap counts was taken as a classification in which nobody had laps to account for; a broken correction kept the newer pipeline version it claimed; a fetch stamped by a fast clock put off every retry; and standings that were malformed or only a first page were reported as none or published as whole. `tests/test_eighth_review.py`; nineteen fixes removed one at a time |
| 9 | The same, asked also about scale, resumption, the contract with readers and the Worker's key handling | `1f0c88c` | Nothing that could publish wrong data. Four findings, three of them where round 8's fixes stopped short. A fetch from before a calendar correction was given the whole identity of a later fetch, the path of its archived feeds included, so it could no longer be loaded; it now keeps its own identity and takes only the calendar's start. A correction was checked for its shape and not for whether its figures could be read, and one unreadable figure stopped the fetch planner; a record is now a measurement only if everything that reads one can read it. A fetch stamped in the future was still asked what F1 had answered last. And the starved fetch batch again: with F1's own host refusing and its mirror serving, the probe said "not answering". Failed fetches are now noted and taken last on the next run, so no session's turn depends on the probe. `tests/test_ninth_review.py`; ten fixes removed one at a time |
| 10 | The same, asked to re-examine the three mechanisms the last rounds added as wholes, and to say which findings need a fault outside the code | `e3ad833` | One finding reachable with everything outside behaving: two runs noting the same failed fetch could leave the older note, which only misorders the next run's fetches. Five that need an object in the archive that nothing here wrote, or a machine with a wrong clock. The one that could publish wrong data: a marker whose start time had been changed to another race's led the build to that race's calendar entry and result, and nothing compared them with the feeds. A build now checks the session it loaded against the entry, by F1's own session information in the archive. The others are closed as a class where they could be: a marker or a correction is read only if every part of it is what it should be, figure by figure, and a fetch cannot be stamped before its session started. `tests/test_tenth_review.py`; twelve fixes removed one at a time |
| 11 | The same, on format 2 for the first time: the models, the normaliser, the telemetry and the analyses' inputs | `d6c0bc5` | Five findings, three of which need nothing but a feed with a hole in it. Wrong data, twice: rows FastF1 adds for a car missing from the car feed were published as the car standing still and counted as coverage, and a lap with no compound in the middle of a stint made two runs that shared laps. A car with positions and no car data was left out of the replay. The other two need an object in the archive that nothing here wrote: a feed status that is no status stopped the fetch planner, and an empty correction claiming a measurement version this code cannot read kept its authority. All five are fixed, and checking the first against the archive (check 14) found three things more, fixed with them: the fix as first written did nothing on a loaded session, a lap whose car data stops short was published with a made-up end, and pit stops reported with no lap were dropped. The frontend's move to format 2 found two: a driver classified without finishing was shown laps down, and a wait through a red flag was a pit stop. Pipeline version 7. `tests/test_eleventh_review.py`; twenty-seven fixes removed one at a time |
| 12 | The same, asked to compare the tests' stand-in sessions with what FastF1 3.8.3 really leaves on a loaded session, and to look hard at what round 11 added | `2b0ebe5` | Eight findings, none of them seen in the 51 archived sessions. Three are forms FastF1 gives a value that the stand-ins did not: the word `None` for a driver with no code, published as a driver called NONE; an empty code on every lap when F1's driver list did not arrive, which failed the build for good; and a zero for a weather reading F1 left out. Four are in what round 11 added: the sample of padding before a lap could be a minute back, and put a minute's travel into the lap's first metre; a correction in F1's pit-stop feed was read as a stop of its own; a report with no lap could be put against a stop the car was not seen to finish; the replay's lap count stood still when the leader's lap had no samples. The eighth is the fourth form of one fault, a correction of a snapshot's record that claims a measurement this code cannot read. It is closed as a class this time: each measurement version keeps its corrections in an object of its own, so there is no such claim to weigh. `tests/test_twelfth_review.py`, with FastF1's own parser and table classes making the forms; the recorded race built with each feed removed (check 15); twenty-nine fixes removed one at a time. Pipeline version 8 |
| 13 | The same, asked to rate by what F1's feeds have been seen to do, and to check on eight real sessions that the artifacts of one generation agree with each other | `4a1944d` | All eight round-twelve fixes hold, and the artifacts agree but for one number. Five findings. One from real data: the count of stops F1's pit-stop feed vouches for, in `coverage.json`, counted a stop F1 sends twice as two (62 beside 33 stops in the 2025 Canadian GP). It does not change which sessions are complete. One plausible and unobserved: a new fetch could load the weather from FastF1's mirror and fail to keep the feed's own lines, and be built with FastF1's zeros; the lines are now asked for where FastF1 asked, and a fetch without them is not archived. Three forms F1 has not been seen to send, closed all the same: two cars with one code, two weather lines with one time, and a stop F1 takes back. Fixed with them, found by the frontend's browser pass and confirmed in F1's raw feed: the zero F1 itself sends for a track-temperature sensor with no reading. `tests/test_thirteenth_review.py`; fourteen fixes removed one at a time. Pipeline version 9 |
| 14 | The same, with the site's reader in scope for the first time (`frontend/src/lib/`), as the other side of the contract: every value the schema allows against what the reader does with it, rule 1 (one generation a view) and rule 7 (another format, a missing file) | `ada5cc1` | The five round-thirteen fixes hold; the dropout rule nulls four readings in 7,428 and Sol agrees with each. The reader passes the contract checks, rule 1 and rule 7. Four findings. One from real data, on both sides of the contract: a lap's distance, FastF1's own, dips by a tenth of a metre while a car stands in its pit box (78 laps in nine published sessions), and the site's lap comparison looked a sample up by distance as if it could not: a lap compared with itself came out 23 seconds apart. The publisher now publishes the furthest the car had been, and the reader matches time into one standstill with time into the other. One plausible and unobserved: where F1's pit-stop feed is read, a stop on lap 1 and a report with no lap in place 1 had keys of one shape and were taken for one stop. Two that need a foreign file: a channel array shorter than its lap, read as "not braking", which the models now refuse to publish and the reader reads as unknown; and a lap whose flags are unknown offered as a clean one. `tests/test_fourteenth_review.py` and `frontend/tests/`; six publisher fixes removed one at a time. Pipeline version 10 |
| 15 | The same, asked what stops the job from running unattended: `python -m f1data run` as a scheduled task on a Windows machine, with the hosted publish workflow beside it | `cc79a2d` | The four round-fourteen fixes hold on both sides, and nothing new in the data. Five findings about the job. A session F1 served and the archive would not take was thrown away with the run's scratch directory and fetched again: a fetch is now made in a spool on the machine and stays there until its marker is in the archive, and the next run uploads it before it asks F1 for anything. FastF1's requests had no time limit, so a connection that went quiet held a run until it was killed, and nothing having been noted of the fetch, the next run began with the same session: requests have a limit, and a fetch is noted when it starts. On the first of January the default scope became the new year alone and last year's unfinished sessions stopped being looked at. A copy of an archive made while a fetch was being uploaded to it could carry a marker without its parts: a snapshot is now copied as its marker describes it, each part checked. And the scheduled-task recipe ran only while its user was logged in. Also from its notes: a run writes down when it ended, and `last-run` says when that is too long ago; a session failing three runs running is named; output is UTF-8; the directory store takes paths of any length and tries a refused rename again. `tests/test_fifteenth_review.py`; twenty-five fixes removed one at a time; a real fetch through the spool built to the generation already published |
| 16 | The same, on the spool the round before added, and reading `docs/data-plane.md` as someone setting the job up on a fresh machine would | `63ce4d5` | Round fifteen's fixes close what they were for; the new code had gaps of its own. A fetch that was whole and could not be written down as whole (a full disk, a kill in that instant) was removed by the handler meant for fetches F1 refused. A fetch with no record yet was swept away at a day old, whether or not a run was still at it. The store named only in `.env`, as the instructions said to name it, was not found, because the file was read after the arguments' defaults. The fetch stage could use a whole run's time before the build. The overdue check had no schedule to run on. Notes of fetches did not tell two runs' attempts apart. And the order of fetches was fair to sessions that fail and not to one that is fetched and short every week. The spool was redesigned: a directory says what it is a fetch of before the fetch starts, a lock is held for as long as a run is fetching into it, and whatever a run leaves is finished by the next from FastF1's cache. On a real session that took three seconds and no request to F1. Read again before it went back for review, the first form of that fix lost the same session one run later: it finished a fetch once whatever had stopped it, and a disk that is full when a fetch ends is usually still full six hours on. A session F1 has served is now marked as that, finished on every run until it is written down, and never removed; a fetch stopped before that is finished once. With little room on the disk nothing is fetched or finished, what is whole is uploaded first, and a run names what it cannot read in the spool, which the guide said it did. The fetch stage has an hour; fetches go in the order of when each session was last tried; a note belongs to its attempt; the publish workflow has its schedule. The guide gained a section on setting a machine up, and nine statements in it were corrected to what the code does. `tests/test_sixteenth_review.py`; thirty-two fixes removed one at a time |
| 17 | The answer to round sixteen: every state a directory of the spool can be in against every way a run can end, for three runs in a row; what carrying a fetch on really does in FastF1 3.8.3; and the guide again | `b9aedef` | One fault of the first rank and seven of the second, nearly all from two decisions of the round before. A run decided what a directory was before it took the lock and acted on that after, so two runs at once could remove a session F1 had served. And a fetch that had been stopped was carried on over the network by the next run, which was a second fetch under the first one's name: it asked the calendar of the day which race a round was, replaced whatever in FastF1's cache of responses had gone stale (everything, after twelve hours), and made its requests where the stage's time limit did not look. The design was changed and not the cases. A fetch has one lock, beside its directory, taken before the directory exists and held through everything done to it; what a directory is, is read under it. A fetch stopped part of the way is removed and made again, so a snapshot is once more of one fetch into an empty cache. A session F1 served is read back from its own cache with every request refused: on a real session with every cached response made stale, five requests were refused and answered from the cache, and identity, coverage and extras came out as the fetch had them, with the cache untouched. The note of a session's fetches lists them, each with its own outcome, and says the same in whichever order two runs write. `run` builds before it fetches, so nothing the fetch stage meets can keep the build from its turn; the stage's time is asked before every upload, reading back, question to Jolpica and fetch; and neither stage goes on asking Jolpica once it has stopped answering. Also: a store's name includes its account, a marker in the way of an upload is that upload's only with its parts in the archive, and no command starts a fetch without room. Three real processes at once over a served fetch: one archived it and two left it. `tests/test_seventeenth_review.py`; fifty-one fixes removed one at a time |
| 18 | The redesign: the lock at every place a directory is made, read, changed or removed, with two and three processes; each state a directory can be left in over three runs; `read_back` against FastF1 and requests-cache as installed; 1,158 orders of three fetches' notes; the guide and the new README | `2679564` | Nothing of the first rank, for the first time since the eleventh round. Three of the second. Where a file can be removed while it is open (Linux, not Windows), a lock file that is removed when its directory goes can be held twice: a run held up for an hour between opening its lock and locking it has it swept from under it, and locks a file no name leads to. A lock now counts only if, once held, its name still leads to the file that was locked; otherwise it is taken again. A whole fetch archived by a later run than the one that made it was never noted as having succeeded, so three such runs would name a session as failing with every fetch of it served: a session F1 served is now noted as fetched by whichever run sees it, however far that gets. And the records the version before wrote were refused under their number, though they say the same things: they are read, a record that really cannot be read fails the run that leaves it, and the guide says what to do with one. Two of the third rank: a part in the archive is taken for the marker's by its bytes and not its size, and a directory marked as served with nothing to say what of is kept. The notes matched their rules in every order tried, and reading back sent nothing. Eleven statements in the guide and the README were corrected. `tests/test_eighteenth_review.py`; sixteen fixes removed one at a time |
| 19 | The eighteenth round's five fixes, the guide and README again, and, asked to look where less attention had gone than the risk warrants, publication and the analyses | `04d0c66` | One fault of the first rank, and it was not in the fetch stage the five rounds before had been about. `fetch` archives whatever session it is asked for, the build built every session in the archive, and what it builds is a race's files: a practice or qualifying session fetched by hand was published with an order by laps completed, laps down and gaps at a flag, and the site showed it. Only a race or a sprint is built now: the builder declines any other before looking anything up, the publisher gives no other a pointer whatever hands it over, and the index shows no pointer to one. Four of the second rank. A lock file was still removed after the lock on it was released, which left a moment for another run to take it and have its name removed from under it: it is removed while it is held, where an open file can be. Reading the records of the version before, which the round before had asked for, was the wrong answer: its directories were kept by other rules (a lock inside the directory, and for a time no mark for a session F1 had served), and read as this version's, a directory another process held could be removed and so could a served session. A record that is not this version's is left exactly as it is, fails the run, and the guide says what to do, with a procedure that now works: it had offered `fetch-due --dry-run` as proof that a session was archived, which it is not, and a name for `archive-directory` that the command refuses. And the car-performance figures leave out the samples at which a car stands still while saying every sample was counted; they say so now (pipeline version 11). `tests/test_nineteenth_review.py`; eleven fixes removed one at a time |
| 20 | The nineteenth round's fixes; then every command and every workflow input asked what it publishes given an input nobody had tried, and the site's view modules asked what they make of a file shaped as the schema allows and no session has been | `196b59c` | One fault of the first rank, the other half of the round before's: a practice session published before that fix stayed published, since a page reached by a session's key reads the pointer and never the index. No such pointer is in the bucket (the live index holds 34 races and 9 sprints). The site now refuses a pointer to anything but a race or a sprint before it asks for the generation, and the publisher passes such a pointer over wherever it counts what is published. Three of the second rank. A lock file that could not be removed while it was held was removed after, everywhere: that is now done only where an open file cannot be removed. F1 has used one name for two kinds of session: the sprint of 2021 was called Sprint Qualifying and was read as the session that sets a sprint's grid, and `fetch --session "Sprint Shootout"` asked FastF1 for a code it does not have for 2023. A session's kind is read with its year, and FastF1 is asked in the words given. And the comparison of two laps' telemetry took each lap's distance to start at nought, where it starts a fraction of a metre either side: two identical laps came out 8 ms apart at the line they both started on. They are laid over each other from what each odometer read at the line. One of the third: the sample server served whatever its directory held. Pipeline version 11 was published by the hosted run to the generations the same sessions built to on Windows (11315 `30cfab1133ba`, 11291 `8130f93d8e77`). `tests/test_twentieth_review.py` and two of the site's test files; fourteen fixes removed one at a time |
| 21 | The twentieth round's five fixes; every way the site reaches a session; the lap comparison after its change; the 2021 rule; the lock once more | `75316e6` | Four of the five fixes stand, with nothing new found in them: no page reads a file of a generation without going through the refusal. The fifth brought a fault of the first rank with it. The comparison took each lap's distance from the line by shifting every place as it was looked up, B's reading at the line plus A's distance less A's reading there. Laid over itself, a lap that reads -1 m at the line and stands in its box at 4,095.1 m was looked up at 4095.1000000000004, a hair past where it stood, and so read as having left: four seconds apart from itself. A lap's distances are now taken from the line once, where its samples are read, and compared as they were before that round; the same lap twice gives the same numbers twice. Seven laps with a standstill and three with a hole, each reading something else at the line, are nowhere apart from themselves. One of the third rank: the sample server's check went by what an address starts with, and `v2/%2e%2e/archive/...` starts with `v2/`. `frontend/tests/telemetry-compare.test.mjs`, `tests/test_sample_bucket.py` |
| 22 | The two fixes of the round before; the guide, the README and the list of what is accepted read as one piece | `cc41dc6` | Both fixes stand, and nothing in the guide contradicts them. One more fault in the lap comparison, older than either: a published distance has one decimal, so a lap that ends a millisecond after a sample of its car has its last two samples at one distance, and was read at the line as arriving there at the first of them. The delta at the line was then 0 where one lap had finished 1 ms after the other. Where lap A ends, lap B is now read at its last sample, and every sample of A at the line reads B at its line and not a rounding error past it. This was the fourth round in a row to find a lap the comparison got wrong, each a shape the tests did not have, so its promises are now also tried on six hundred laps nobody chose, made with everything a published lap has been seen to have in every combination: a lap is nowhere apart from itself, two laps start together, the delta at the line is the difference between the lap times either way round, and no sample is left without the other lap beside it. That test fails on each of the three versions of the comparison before this one. `frontend/tests/telemetry-compare.test.mjs` |
| 23 | The round before's fix; the lap comparison against its own header as a specification; the site's other view modules; and one question of method, how to tell a pit stop from a car that only went down the pit lane | `dd404c7`, then `2c663f7` | The first attempt stopped four minutes in with "Your workspace is out of credits" and wrote no report. An independent reader (a Claude agent, given the code and no conclusions) went through the view modules in its place: the table below, fixed in `2c663f7`. With credits back the round was run on that commit. Both earlier fixes stand and so does every change of `2c663f7`. It found four faults of the first rank and two of the second, all but one of them the same thing counted three ways: a car that goes down the pit lane without stopping. See "A pit stop and a passage" below. The other is in the lap comparison: the delta at the line is between the two laps' telemetry, and a first lap's published time is from another clock. In the 2026 Australian GP Albon's first lap is timed at 1:39.376 and Bearman's at 1:39.765, 0.389 s apart, and their telemetry ends 0.455 s apart. Measured over the nine sessions in the local store, the telemetry of every lap after the first runs for its lap time to the millisecond, but for one (below); a first lap's runs a quarter of a second longer in most races, and in the 2026 Dutch GP between 1.4 s shorter and 0.3 s longer from car to car. The telemetry is the one clock both cars are on, so the delta stays on it; the module's header no longer promises the difference of the lap times, and the comparison names any lap whose telemetry does not run for its lap time, with both figures. One such lap is not a first lap: Lindblad's lap 5 of the 2026 Dutch GP is timed at 1:27.335 and has telemetry for the last 31.6 s of it. And a hole in lap B that fell between two of lap A's samples was drawn straight across, since B read well at both: a row with nothing for B is now put between them, as one already was for a hole in A. Pipeline version 12 was published by the hosted run to the generations the same sessions built to on Windows (11315 `5ff1f94f76d3`, 11291 `4a32fa668ac0`, 9963 `5de7e86b0673`), and the deployed page for the 2025 Canadian GP then read 33 pit stops, 53 stints and a pit-lane median of 23.656 s. `tests/test_twenty_third_review.py`, `backend/tests/test_analysis_methods.py`, two of the site's test files; twenty-eight fixes removed one at a time, each caught |
| 24 | The six fixes of the round before; the strategy analysis read as a reader of the page would | `b1a6aed` | All six close what they were for, and nothing was found in the renumbering, the pit-lane figures or the row that marks a hole of lap B. Four more of the first rank, each smaller than the round before's, and three of them where that round's fix had been written twice. The analysis and the site had each been taught what an entry to the pit lane was, in their own words, and they disagreed about a car that waited there through a red flag: the site calls that a wait whatever was done to the car. The analysis took one whose tyres were changed for the driver's first stop (Norris, lap 2 of the 2026 Dutch GP, whose stop on lap 21 and its 1.852 s were never shown), and one whose tyres were not for a car that went through without stopping (three cars of the 2025 São Paulo sprint, which waited 22 minutes). The analysis now reads the stop list in the site's order, a wait first, and leaves a wait out of pit loss as a wait. The clock note of the round before was said lap by lap, so it was said of two first laps whose clocks are out by the same amount, which most of one race's are, and of a lap laid over itself: pairs whose delta at the line is the difference between their lap times. It now goes by the two differences and gives both. And "Compounds used: 3" for the 2025 Miami GP, run on two: the analysis counts the stints F1 named no compound for under a key of their own, and the page counted the key. One of the third rank: a driver whose stint numbers from F1 went back down after a passage could come out with a set numbered nought, or two sets with one number. No archived session has such a driver (Sol read all 77 snapshots); a driver whose numbers do not only go up now keeps them as F1 gave them. Pipeline version 13. `tests/test_twenty_fourth_review.py`, `backend/tests/test_analysis_methods.py`, two of the site's test files; thirteen fixes removed one at a time, each caught |
| 25 | The five fixes of the round before; then every number the site prints for a session that no earlier round had checked against the archive, each asked what it counts and whether the words beside it say that | `3b539af` | All five fixes stand, with nothing new found in them: over 1,614 archived entries to the pit lane the analysis and the site disagree about none but the accepted one, and over 216,995 pairs of laps the clock note is said where the two differences differ and nowhere else. Pipeline version 13 was published by the hosted run to the generations the same sessions built to on Windows (11315 `2c26dfcd6a67`, 11353 `ad12fa6bb94d`). Of the numbers gone through (the overview, results, lap times, race pace, tyre degradation, the team-mate comparison, track dominance, corner analysis, car performance, weather, the replay, the season and meeting pages, the standings), three had words beside them that said something else. None is a wrong number; each was a number under the wrong name, and each is older than this branch's work on the page it is on. "Laps fitted: 23" beside "Outliers: 1" for Antonelli's second stint of the 2026 Austrian GP, whose slope is fitted to 22: the table now gives the laps the fit is of, and none for a stint no fit was made of. "Quicker on the new tyres" across a stop the car left on the tyres it came in on (Sainz in the 2026 Dutch sprint, who stood for 8.4 s on lap 16): the pace change is said to be after the stop, and a stop F1's tyre data has the car on the same set after is marked. And "0 clean laps, and at least 8 are required" for Bearman's third stint of the 2026 Barcelona GP, 19 clean laps on a set that went on used, for which F1 gives no tyre age: the row now says it is short of ages. Pipeline version 14, for the words in two of the analyses. `tests/test_twenty_fifth_review.py`, `backend/tests/test_analysis_methods.py`, two of the site's test files; seven fixes removed one at a time, each caught |
| 26 | The three fixes of the round before; any printed figure no round had yet checked; and every sentence the analyses publish beside their figures, asked whether it is true of the data it is published with | `dcf382d` | The three fixes stand over all 51 archived sessions: of 2,266 tyre-degradation rows every count of laps fitted is the count the slope is of, all 14 stops on the same set are marked and no other, and all 35 stints short of tyre ages say so. Pipeline version 14 was published by the hosted run to the generations the same sessions built to on Windows (11315 `9ed9d1a1f52b`, 11307 `7aaed4672b1b`). Three published sentences were false of some race, and one card. "Each within 3 laps of the driver's first stop", of a lap four lap numbers after it (Alonso in the 2026 Australian GP, compared across laps 10 and 15 around a stop on lap 11; 62 rows in 14 sessions): the three are counted from the out-lap, and the sentence now says where each lap is looked for. "No clean green-flag lap within 3 laps after the stop", of a driver who ran one (Ocon in the 2025 Qatar GP, who stopped on laps 8 and 9 and ran a clean lap 11): the search ends at the driver's next stop, and the row now says that it did. "The 10% of matched laps with the largest difference each way are dropped", of five matched laps, of which the one dropped each way is a fifth (25 rows in 11 sessions): the sentence now gives the rule whole, a tenth and never fewer than one. And lap B's "Maximum speed" under the lap comparison was read from lap B as it is laid under lap A, between its own samples: Verstappen's lap 57 of the 2026 Austrian GP showed 319 km/h as lap B and 320 as lap A. It and the share at full throttle are now each lap's own, from its own samples. Pipeline version 15, for the sentences. `tests/test_twenty_sixth_review.py`, `backend/tests/test_analysis_methods.py`, `frontend/tests/telemetry-compare.test.mjs`; eight fixes removed one at a time, each caught |
| 27 | The four fixes of the round before; then whatever sentence that states a number or names a population was still unchecked, in the analyses, the coverage, the manifest, the pointer and the index, and in every sentence the site composes from the data | `cffee04` | The four fixes stand, checked over the archive: all 830 pace-change rows use laps where the caveat says they are looked for, all 186 rows with no value give the true reason, all 495 team-mate rows are trimmed as the sentence says, and for all 49,378 published telemetry laps the figures under the comparison are the lap's own on either side. Pipeline version 15 was published by the hosted run to the generations the same sessions built to on Windows (11315 `bc6f338acf96`, 11234 `9d5b9ab012e2`). Sol reports that within that scope no statement of a number or a population remains unchecked, and that two are false, both older than this work and neither a wrong number. "1368 timing laps" on the home page for the 2026 Dutch GP, which F1's timing has 1,366 of: the count is of the lap table, which has a row FastF1 adds for the lap a car stopped on. It is called laps. And "no stationary times for 20 stop(s) in the timing" for the 2025 São Paulo sprint, of 20 entries to the pit lane of which 18 are waits through a red flag: the shortfall says entries. Nothing else at the two higher priorities, by any route. Pipeline version 16, for that sentence. `tests/test_coverage.py` |
| 28 | The two fixes of the round before; whether the claim that no statement remained unchecked still held; the descriptions in the schema | `4af8d80` | Both fixes stand, the claim holds, and nothing else at the two higher priorities. One description in the schema was false: a lap's throttle is "0 to 100", and Albon's lap 2 of the 2026 Australian GP is published with 104. Sol asked for the description to be corrected and the values kept. Looked at over the nine sessions in the local store, the value is not a throttle. 104 is what F1's car feed sends, for the throttle and for the brake, of a sample it has no pedal reading for, while it repeats the speed and the engine speed it last had: of 2,698 such samples in three races, 2,667 have the brake "on", and in two of three stretches of more than one sample the speed does not change at all. FastF1 passes the throttle on and makes the brake a yes. So 422 of 10,458 published laps had a stretch, 530 of the 635 stretches under two seconds, drawn as full throttle and braking at once: Albon's lap 7 of that race for 1.6 s at 302 km/h. The car-performance figures counted those samples as braking, and the corner analysis could take one for where a driver began to brake. A lap's throttle and brake are now unknown at such a sample, and between it and the next, in what is published and in what the analyses read; the rest of the sample is as F1 sent it. The site already drew a channel with no entry as a gap. This is the second time in these rounds that a wrong description was the visible end of wrong data (the first was the pit-lane median), and the reason each finding is looked at in the archive before it is answered. Pipeline version 17. `tests/test_twenty_eighth_review.py`, `frontend/tests/telemetry-compare.test.mjs` |
| 29 | The fix of the round before, and whether 104 is what it was taken to be, from the raw car feed in the archive | `1ce215c` | Not completed: Codex stopped about half an hour in with "Your workspace is out of credits" and wrote no report. Pipeline version 17 had by then been published by the hosted run to the generations the same sessions built to on Windows (11234 `b067dd8cd883`, 11315 `2801800370ba`), and all 43 published sessions are at it. What Sol had run by then is in its log, and settles the question it was asked. It read the raw responses of F1's car feed out of the archive and counted the pairs of throttle and brake that have a 104 in them. In every session the bulk are both at once (90,090 of 91,687 in the 2026 Australian GP), with the speed the same as the sample before in all but a few dozen: the reading of 104 as no reading stands. But F1 sends the mark in each channel by itself too. A throttle of 104 beside a real brake is rare (13 samples in that race). A brake of 104 beside a throttle in range is not: 1,584 in that race, 941 of them inside laps. That was left open when the round stopped, and is closed in the commit after it (below): a build reads the brake's own mark from F1's raw car feed. Pipeline version 18. `tests/test_carfeed.py`; twenty-one parts of it removed one at a time, each caught |
| 29, begun again | The fix of the twenty-eighth round and the reading of the raw car feed that followed it; whether 104 is what it was taken to be, in each channel; whether reading the raw responses keeps a build a function of the archive | `cf96efa` | The reading of 104 stands in both pedals: over twelve sessions and 8,376,528 raw samples a brake is 0, 100 or 104 and nothing else, and a throttle has nothing outside 0 to 100 but 104. Every car of every session checked passes the test by which the raw feed is believed, so the fallback was needed nowhere; no build crashed and no throttle over 100 is left. Pipeline version 18 was published by the hosted run to the generations the same sessions built to on Windows (11234 `0fa73b9d7aad`, 11315 `7a8ff1128771`), with no warning of a raw feed it could not use for any of the 43. Two faults of the first rank and one of the second, each a consequence of the last two rounds or beside them. A gear that is no gear: in the 2026 Dutch GP car 1 sends a "gear" between 9 and 40 for fourteen seconds, standing in the pit lane, and Norris's lap 4 was published with twenty of them. A gear over 8 is now no reading, as a pedal at 104 is. A corner with no brake reading on the way in was published as a corner the driver did not brake for, since a brake that is not known had been made to count as off: Gasly's lap 56 of the 2026 Australian GP has no reading for the 365 m before turn 9, from 311 km/h to 218, and the page said "No braking". A row now says whether its braking is known. It is not where no braking is seen and the approach, from half-way back to the corner before, has a sample with no reading; nor where the braking is first seen at the sample the reading comes back on, which is not where it began, and then the brake point and what is counted from it are left out. And the raw responses were loaded into a database in memory, which Python can do only where its SQLite was built to allow it: they are opened as a file. Sol also noted, at its third rank, that reading a record of a response could run whatever a foreign record named; the records the HTTP cache writes name nothing, so the reader now refuses any that does. Pipeline version 19. `tests/test_twenty_ninth_review.py`, `tests/test_carfeed.py`, `backend/tests/test_corner_analysis.py`, two of the site's test files; fifteen fixes removed one at a time, each caught |
| 30 | The three fixes of the round before; every figure derived from a lap's throttle, brake or gear now that each can be missing | `7960ca0` | All three fixes stand: no gear outside 0 to 8 is published and none inside it is left out, in the parsed car feeds of all 51 sessions; the corner fix closes what it was for; and all 1,166 records in the 77 files of raw responses in the archive are read by the reader that refuses a record naming anything to load. Pipeline version 19 was published by the hosted run for 47 sessions: the 43, and the 2026 Monaco, Hungarian, Spanish and Bahrain GPs, whose time to be published as partial had come. Two faults of the first rank, both in the corner analysis and both in the 2026 Australian GP. One is older than this work. A braking's slowest point was looked for up to 250 m past where the brake came off, whatever lay there: Albon's light braking for turn 12 on lap 36, from 204 km/h, found the 108 km/h of the braking for turn 13 that follows. Turn 12 was published as not braked for, and turn 13 with turn 12's brake point, 287 m before it. A braking's slowest point is now looked for before the next braking begins: turn 12 is 204 to 180 km/h over 73 m, and turn 13 is 199 to 88 over 103 m. The other was in the caveat of the round before, which said of a driver that it is not known whether they braked where they were seen braking, only from the sample the reading came back on (Russell into turn 1). A corner row now says which of four things the feed shows (`braking`): seen from where it began; none; begun where there is no reading, so that the driver braked from a point that is not known; or not seen with part of the approach unread, so that whether they braked is not known. The page and the caveats say each apart. Pipeline version 20. `backend/tests/test_corner_analysis.py`, `tests/test_twenty_ninth_review.py`, one of the site's test files; ten fixes removed one at a time, each caught |
| 31 | The two fixes of the round before; whether the corner page says what its archived data shows, over 4,880 corner rows of 16 sessions | `03f26a7` | Both fixes stand, and pipeline version 20 was published by the hosted run for 47 sessions. Three faults of the first rank, all in the corner table. A corner the driver braked for was still published as not braked for whenever its braking was counted for another corner. Brakings were found along the whole lap, two applications within 80 m were one, and the one corner its slowest point fell in was given it: Albon's lap 78 of the 2026 Monaco GP comes off the brake at 79 km/h for turn 5 and goes on again 74 m later, at 140 km/h, for the hairpin, and Alonso's lap 15 of the 2026 Australian GP takes 250 km/h down to 222 for turn 9 and brakes again 67 m later for turn 10. Turns 5 and 9 said "No braking". This was the third round running to find a fault in how a braking is given to a corner, so the rule was changed and not the case. A corner's braking is now looked for in the corner's own stretch of the lap, from half-way back to the corner before to half-way on to the next: a braking is the corner's when the brake is on there before the corner, or when the car, slowing from it, is at its slowest there, so a braking through two corners is given for both from the one brake point; and the brake going on again is the same braking only within 80 m and only if the car has not gained 8 km/h since it came off. The inputs of the analysis were saved for all 51 archived sessions and the old and the new run over them. They are a build's inputs but for the first-lap times a build takes from the classification, so a driver whose quickest timed lap is the first is read on another lap in this count, or on none: the counts are of the rule, on 21 of Monza's 22 drivers, and not of the published files to the row. Of the 16,395 rows of the 49 sessions whose corners are the circuit's own, 14,129 are as they were. 1,558 that said "No braking" have the braking that was there: turn 5 at Monaco for 16 of 22 drivers, the first corner of Monza for 18 of 21, turn 1 at Suzuka. 183 have a brake point of their own where they had the corner before's: Monaco's hairpin, from 212 km/h with the brake "on" for 14 seconds, is from 140 km/h for 2. 70 that said the brake had no reading have a braking, 35 of them from where it began. A corner not braked for has its slowest point looked for before the brake next goes on past it (221 rows), where it could be a point well into the next corner's braking. The same comparison showed a brake that reads on while the car gathers speed: on Stroll's lap 36 of the Australian GP for 636 m, most of it at full throttle, from 150 km/h up to 253 and down to 189 for turn 6, which said "No braking" because the car lost nothing from where the reading went on. What a braking takes off is counted from the fastest the car is under it, and such a row says the driver braked from a point that is not known (8 rows). What is left that a reader could question, counted over the 47 sessions without a repeating feed: 18 rows say "No braking" where the brake was on and took less than 8 km/h off, which the caveats now give as the least that counts. The second fault: the site read only the newer word for what is known of a corner's braking, so a generation of pipeline 19, still served while sessions are rebuilt, said "No braking" where it had said there was no reading; the older word is read where the newer is absent. The third: the table put a corner's distance along the lap the corners were placed on beside a brake point along the driver's own lap, 36 m apart for Stroll at turn 6 of the 2026 Austrian GP. Each row now carries where its own lap has the corner (`corner_distance_m`), and the telemetry chart, which drew its corner lines at the same borrowed distances, places each where the lap drawn passes the corner. Pipeline version 21, published by the hosted run for 47 sessions. Of what it published: the corner analysis of the 2026 Austrian GP is byte for byte the file this machine builds, and those of the 2026 Monaco and Australian GPs and the 2025 Japanese and Monaco GPs are row for row what the comparison above computed; Monaco's turn 5 and hairpin say "seen" for all 22 drivers, and Monza's first corner for 21 with one braking begun unread. `backend/tests/test_corner_analysis.py`, `tests/test_thirty_first_review.py`, three of the site's test files; twenty-eight fixes removed one at a time, each caught. A follow-up (`cec89c5`) puts a lap's line on the distance as published, which is the chart's axis, where the commit had it counted from the line, a fraction of a metre off |
| 32 | The three fixes of the round before; the corner table and the telemetry chart's corner lines as a reader takes them | `8e31d99` | All three stand: the Monaco, Australian and Monza cases reproduce, rows of pipelines 19, 20 and 21 read correctly on the site, and Stroll's Austrian turn 6 carries 2,553.8 m. Two faults of the first rank, both in what the round before added. Whether the brake going on again is the same braking was judged by the car's speed at the two ends, and missed a car that goes on slowing after the brake comes off and then gathers speed. On Bearman's lap 49 of the 2025 Japanese GP it comes off at 91 km/h in the chicane, the car slows to 85, gathers speed to 103, and the brake goes on again at 97, for 8 m: the two were one braking, and the second part of the chicane was published as braked for from 255 km/h, 144 m back. What the car gains is now looked for at every sample between the two, from the slowest it has been since the brake came off. Over the saved inputs of the 51 sessions that changes 112 rows: most are the second part of a chicane that now has a brake point of its own (turn 5 in Mexico City, the bus stop at Spa), and in 6 the second application takes less than 8 km/h off and the row says "none", Bearman's among them. The other fault: the telemetry chart looked for a corner within 200 m of the corner map's distance along the lap, and a lap can be further out than that all the way round. Alonso's first lap of the 2026 Austrian GP is counted from the grid and has turn 6 at 2,765 m, 247 m on: the pass was thrown out, the line drawn at a sample 49 m early that happened to be in reach, and turn 8 not drawn. That was in the site, written the round before. Looked for in the analysis, the same rule was there, older than these rounds, and did the same to whole laps whose distance runs long after a stretch with no car data: over the saved inputs, 15 rows outside the two sessions with repeating feeds had a corner 19 to 50 m from where the lap's line passes it (Colapinto's lap 53 of the 2026 Italian GP, Bearman's lap 20 of the 2026 Japanese GP, Alonso's lap 25 of the Chinese GP, and first laps). Both now place a lap's corners together. Each time the line comes within 50 m of a corner is a pass; how far the lap's own distance is out is measured from the corners it passes once; and a corner is the pass nearest it within 200 m of where that puts it. A lap that went from line to line and has no pass there has the corner where its line comes nearest. The same search showed a lap given figures for corners it did not take: Antonelli's lap 9 of the 2025 British GP ends down the pit entry, 99 m from turn 17 and 92 m from turn 18, and was read at their distance. A lap is now read by distance only where it has no position data, and a whole lap not seen at a corner has no row for it and is named in a caveat. In the 2026 Hungarian GP, whose position feed repeats itself, that takes out 128 of 336 rows, which were figures from places the car was not seen at. The chart was then checked against what is published, over every lap of five sessions (4,565 laps, 66,000 lines): each line stands where the lap's line passes the corner, but where both feeds freeze with the car in a corner and the lap's distance runs on while the car does not, which is the known fault of a repeating feed. Pipeline version 22. `backend/tests/test_corner_analysis.py`, `tests/test_thirty_second_review.py`, two of the site's test files; twenty-two fixes removed one at a time, each caught |
| 33 | The two fixes of the round before; whether the table and the chart put a corner in the same place | `ce1b7d1` | Both fixes stand: across 3,320 pairs of brake applications no merge or split contradicts the stated rule, the search-window cases are closed, and no whole lap that plainly passes a corner lacks its row. Pipeline version 22 was published by the hosted run for 47 sessions, the Austrian GP's corner analysis byte for byte this machine's. One fault of the first rank left. The analysis put a corner at the nearest sample of the lap, where the chart puts it where the line between two samples comes nearest. Either feed can miss a second, and the two then stand tens of metres apart: Piastri's lap 61 of the 2026 Dutch GP has turn 14 at 3,922 m in the table and 3,884 m on the chart. The analysis now places a corner as the chart does, between two samples where that is nearer, on a line that is not drawn across a hole of more than 150 m on the ground. Table against chart, on the published laps of nine sessions: of 2,953 rows none is more than 15 m from the chart's line, where 9 of 1,108 were in the three sessions Sol named. Placing corners between samples moved every one of them by a metre or so, and that showed what the rule of round 31 turned on. 35 rows went from braked for to "none" because a sample now fell the other side of a line: the corner itself (a brake that goes on 3 m past turn 5 in Bahrain and takes 33 km/h off in turn 5's stretch), or the half-way point to the next corner (the second part of a chicane whose slowest sample is a metre short of its stretch). The rule is replaced by one that turns on how much the car slows. A braking is a corner's when the car is still slowing from it in the corner's stretch, which it is until it has gathered 8 km/h from the slowest it has been, until the next braking begins, and no further than 250 m past where the brake came off; and it is counted when it has taken 8 km/h off the car by the corner's slowest point. Against what was published, over the saved inputs: 1,001 rows that said "none" have a braking, most of them one that begins past the corner in its stretch, where the row now shows a brake point after the corner's place, or the second part of a chicane the car comes into still at its slowest; and 28 that had one say "none", each a corner the car was driven on to and then lifted for (the last corner of Suzuka for Piastri in 2025: 84 km/h, off the throttle, no brake). The chart had also lost its corner lines on laps published without position data, which is most of the 2026 Monaco GP: such a lap has them by distance, and the chart says that they can be tens of metres out. Pipeline version 23. `backend/tests/test_corner_analysis.py`, `tests/test_thirty_third_review.py`, one of the site's test files; thirteen changes removed one at a time, each caught |
| 34 | The fix of the round before, the rule that replaced the one of round 31, and the chart's lines on laps without positions | `a178c06` | Nothing at the first or the second rank. The finding is closed: the three laps Sol had named have the table within 2.5 m of the chart (Piastri's turn 14 at 3,884.0 m against 3,883.8 m). Over 6,935 rows of 21 sessions, by a calculation of its own, it found no braking that qualifies and is missed, none kept after the car had been driven on, and no brake point, entry speed, slowest point or duration that differs from the lap's samples by the rule the caveats state; no caveat false of its rows; and the chart's lines by distance on laps without positions as described. Outside one lap the largest difference between table and chart is 10.8 m. The one lap is Hadjar's lap 4 of the 2026 Miami GP, his representative lap, on which the position feed repeats readings and jumps some 400 m back while the car feed goes on: turns 6 and 9 stand 144 m and 726 m apart in table and chart. Sol set it under the known fault of a feed that repeats itself. It is recorded here because the session is not one of those known for it, and the lap is the same one the two rounds before turned up at turns 4 and 16. Pipeline version 23 was published by the hosted run for 47 sessions. Of the 45 with the circuit's own corners, the published tables were then set against the chart's lines on the published laps: of 14,890 rows 53 are more than 15 m apart, 51 of them in the 2026 Hungarian GP and the other two Hadjar's |
| 35 | A comment on the pull request, read against the code and not run: what notices the fetch job not working, and what a reader is told of a feed that repeats itself | `6c82ca7` | Nothing in how the archive is written or a publication made. Three findings. The check the hosted workflow makes of the fetch job was told to let "never" pass, on every schedule and for good, so a job that was never installed left the workflow green: it now fails, and "never" passes only while a repository variable says the job has yet to run for the first time, with a warning on every run that it does. The same check read when the last run ended and printed how: a job that ran on time and failed every time passed. A run's record now counts the runs that have failed one after another; one is said and let pass, since F1 refuses a fetch now and then and the next run makes it good, and two running, the same two turns of the schedule that make a job overdue, fail the check. A record that does not say how its run ended vouches for nothing. The third is the item these rounds had left as known and not built: a feed that repeats itself met every bar. It is now counted, lap by lap, for the car feed and the position feed apart (`car_repeating_laps`, `position_repeating_laps`), and a driver with more such laps than may be missing leaves the session partial on `car_data_repeats` or `position_repeats`; the session's page names the drivers and says what of theirs is not reliable. The count is of FastF1's tables as loaded, and was first set against the figures above: the share of moving samples that repeat comes to 14.3% for the 2026 Chinese GP and 12.8% for the Japanese, as counted from the raw feed. Over the nine races of 2026 whose feeds are on this machine (Australia to Britain, 10,406 laps) a lap with nothing wrong has under one car sample in a hundred repeating, and the worst lap of the Monaco, Canadian, Barcelona, Austrian and British races has 5, 12, 21, 11 and 20; no lap of those five is over a quarter. Japan has 167 laps over a quarter and 20 drivers short, China 132 laps and 11 drivers, Australia 6 laps and one driver (Russell, 4 of 58). The position feed has one such lap in the nine races: Hadjar's lap 4 of the Miami GP, the lap rounds 32 to 34 each turned up. So four of those nine races have a driver short on one of the two bars. Not counted here, for want of their feeds on this machine: the Hungarian GP, the Chinese sprint and the other 40 sessions. No session is fetched again for this; a build counts the laps from the feeds it has loaded, writes them beside the snapshot and decides again. What is left as it was: the corner analysis and the car performance still read each driver's fastest lap whatever the state of its telemetry, and a session short on these bars is fetched again weekly like any other that arrived short. Pipeline version 24, not yet published by a hosted run. The golden file of the Austrian race (`tests/fixtures/golden-11315.json`) is as it was recorded and wants recording again against the archive, since `coverage.json` has two more figures for each driver. `tests/test_thirty_fifth_review.py`, `frontend/tests/coverage.test.mjs`; twelve fixes removed one at a time, each caught |

**The 2026 Hungarian GP is published, as partial, and its telemetry is not to be relied on.** That is the item above under "What real data changed": two of five sessions have feeds that repeat themselves, and no bar sees it. It is recorded again here because the session is now live, and because the raw car feed has since been counted for all 51 archived sessions. Of the samples sent while a car is above 30 km/h, the share that repeats the engine speed and the road speed of the sample before is between 0.3% and 1.6% in every session of 2025 but one sprint, and in 2026: 57.5% in the Hungarian GP, 30.7% in the Chinese sprint, 14.3% in the Chinese GP, 12.8% in the Japanese GP, and under 8% elsewhere. Part of that carries F1's mark for no pedal reading and is now published as such; what does not is 37.8% in Hungary, 10.5% in the Chinese sprint, 6.6% and 5.2% in the Chinese and Japanese GPs. In the Hungarian GP as published the brake's figures are sound again (a braking share of 15% to 32% by driver, where FastF1's table gives 47% for the race), but the corner analysis is not: of its 336 rows 188 are marked as braking not known, and others stand at speeds no car reaches there, since the position feed repeats too and a corner is found by position. The session says it is partial for a driver's tyre data, which is not this. A bar for a feed that repeats itself was the thing not built until round 35, which counts the laps and publishes such a session as partial for them.

**The brake's own mark, which that round left open, and how it was closed.** FastF1 reads the brake as a yes or a no, and anything over nought is a yes, so a brake of 104 reaches this code as `True` with nothing to tell it from braking. The fix of the twenty-eighth round caught it where the throttle is marked too. What it left, counted by Sol from the raw feed inside laps: 13 samples in the 2025 Japanese GP, 148 in the 2026 Austrian GP, 941 in the 2026 Australian GP, and 92,017 in the 2026 Hungarian GP. The first record of this said the Hungarian GP's brake had no reading "for most of the race". That was written from the one count and was an overstatement. Measured since: 28.5% of that race's samples in laps have no brake reading (267,618 of 938,006), of which FastF1's table alone shows 8.9%; handed on as FastF1 has it, the brake is on for 47.1% of the race, and of the samples that have a reading it is on for 25.9%. In the 2026 Australian GP the figures are 2.8%, and 18.9% against 16.5%; in the 2026 Austrian GP 0.2%. The Hungarian GP was not published while this was open: it is one of the eight sessions held for a shortfall at the source.

A build now reads the raw value. The archive keeps F1's raw responses beside FastF1's cache of them (`http-cache.sqlite.gz` in each snapshot), which no build had read. `read_raw_response` in `f1data/archive.py` takes the car feed out of it, `f1data/carfeed.py` reads each car's samples and which pedal of each carries the mark, and a lap's throttle and brake are each unknown by their own mark: the throttle at a marked sample and on the line drawn to or from it, the brake from a marked sample until the next that has a reading. The raw feed is believed only if it is plainly the one FastF1's table was made from, which is checked by what both can see: every sample F1 sent is in it, and it marks the throttle exactly where the table shows the mark. In the 2026 Australian GP that holds for all 31,179 samples of each of the 22 cars, with twenty of each car's a millisecond apart, because FastF1 cuts a date to the microsecond before it rounds it. A raw feed that fails the check, or a snapshot with none, leaves the build as it was after the twenty-eighth round, and says so in its log. It costs a build about a second and a half. `tests/test_carfeed.py` writes an HTTP cache with the library FastF1 uses and reads the feed back out of it, so that a change to how that library keeps responses is met in a test.

What that reading of the view modules found, each reproduced before anything was changed:

| Where | What a page said | What was done |
| --- | --- | --- |
| `teammate-view.ts` | "RUS quicker by 0.000s" for the 2025 Canadian GP, where the two Mercedes averaged 1:15.5212 and 1:15.5213: the gap is published to a tenth of a millisecond and printed to a whole one | Level, when the gap rounds to nothing at the precision printed |
| `format.ts`, the session heading | "Mar 7, 2026 · Melbourne, Australia" for a race on 8 March, to a reader in the Americas: the start as a bare date in the reader's zone, a day off from the meeting's own | The start with its time and the zone named; a session with only a day is given that day |
| `format.ts`, lap times | `1:60.000` for an average of 119,999.6 ms: split into minutes and seconds before it was rounded | Rounded first. No published value hit it |
| `session-summaries.ts` | "Finish P4" on the card of a car that never left the grid, when the result is the provisional order | A provisional order is labelled as the running order, and a car with no lap has no place in it |
| The calendar's words | "Run, and not published yet" from the moment a session starts, so for the two hours a race is on | "Started or run" |
| `strategy-view.ts`, relaying the strategy analysis | "82 of 83 stops timed", median 18.3 s, for the 2025 Canadian GP, where the field followed the safety car down the pit lane on lap 67 and 49 of the 82 entries are that; "fastest 12.1 s" for the 2026 Dutch GP, which is a drive-through penalty | The words, in `2c663f7`; the figures, after the twenty-third round. See "A pit stop and a passage" below |
| `standings-view.ts` | The race named beside "After round N" is found by Jolpica's round number in the site's calendar, which would name the wrong race if the two numberings ever differed | Left. They have not been seen to differ |

**A pit stop and a passage.** `pit-stops.json` is every entry to the pit lane the timing shows, and not every entry is a stop. In the 2025 Canadian GP the field followed the safety car down the pit lane three times in the last four laps: 49 of that race's 82 entries. The independent reading found the pit-lane figures taken over all of them (a median of 18.3 s, of cars that never stopped) and left it open as a question of method. The twenty-third round answered the question and found what else counted a passage as a stop:

| What was published | What it is now |
| --- | --- |
| Six stints for Verstappen in that race, where he ran three: F1's tyre data gives a car a new stint number each time it goes through the pit lane, tyres changed or not | A lap keeps the number of the set it is still on when F1's tyre data says it is the same set: under the new number, the same compound and one lap older. The numbers after it close up. Over the 51 archived sessions this takes 164 stints away: 49 in that race, 43 in the 2025 Australian GP, 35 in the 2026 Monaco GP |
| "83 pit stops" on the session's overview and its strategy page | An entry says whether the tyres were changed (`tyres_changed`, from the stints), and the site counts as a stop an entry F1's pit-stop feed times or after which the car is on another set. A car that went through is listed as that, drawn as that on the timeline, and counted apart |
| A pit-lane median of 18.3 s and a fastest of 18.1 s for that race; a fastest of 12.1 s in the 2026 Dutch GP, a drive-through penalty | The pit-lane figures are of the stops F1's pit-stop feed gives a stationary time for: 23.7 s and 23.0 s, and 17.2 s |
| That drive-through priced as a pit stop, at 13.0 s, in the Dutch GP's pit-loss median | An entry both feeds say was no stop is left out of pit loss, with the reason. The estimate moves in five sessions, by 0.12 s at most |
| Each driver's "first stop" in the 2025 Australian GP taken to be lap 2, when the field followed the safety car down the pit lane, so that the pace change across the stop they did make was never worked out | The first entry that was not a passage. It changes for 22 drivers in five sessions |

The rule, and why it is two rules. A figure that is the time of a stop needs to be sure of every stop in it, since its fastest is one entry: so the pit-lane figures take only what F1's pit-stop feed reports, and leave out the one stop in eleven that feed misses (116 of 1,327 in the archive, which the tyre data shows; the count on the page says so). A count, or what is left out of an estimate, needs to be sure of what it leaves out: so an entry is taken for a passage only when both feeds say so, no stationary time and the same set of tyres afterwards (147 entries in the archive). A car in the pit lane while the session was red-flagged is a wait before it is either, whatever was done to it there. The analysis (`_not_a_stop` in `backend/app/analysis/strategy.py`) and the site (`pitEntryKind` in `frontend/src/lib/strategy-view.ts`) read the stop list in that one order; the twenty-fourth round found them reading it in two. Neither feed is enough alone, and each was tried. Timing alone does not separate a quick stop from a slow passage in the 2025 Australian GP, where they meet at 14.8 s. The tyre data alone is wrong in the 2025 Miami GP, where it starts on lap 24 and shows each change of tyres eight laps late: it has the car on the same set after twelve stops the pit-stop feed times. That was found by running the first version of the fix over the whole archive before publishing it. Race control's messages were considered and not used: a message that the field is to follow the safety car through the pit lane does not say which cars did, and a drive-through penalty is announced when it is given, not when it is served.

What is still wrong, and known. F1's tyre data has a new set going on at four entries too quick to have been stops (Stroll's lap 4 of the 2025 Australian GP at 14.5 s, Antonelli's lap 12 of the 2025 Miami sprint at 18.4 s, where he drove through after an unsafe release ahead of him, Russell's drive-through on lap 53 of the 2025 Monaco GP at 19.4 s, and Lindblad's lap 5 of the 2026 Dutch GP at 12.2 s). Each is counted as a stop and has a stint beginning after it, as F1's tyre data has it; none is in the pit-lane figures, since the pit-stop feed reports none of them. A set that went on used has no age in F1's data, so a car that drives through on one keeps the new stint number. And where F1's pit-stop feed leaves a whole team out, as it does Aston Martin and Williams in the 2026 Austrian GP, that team's stops are in no pit-lane figure.
