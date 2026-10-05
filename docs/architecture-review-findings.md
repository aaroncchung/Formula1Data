# Architecture review findings

## 1. Review metadata

| Item | Value |
| --- | --- |
| Repository | `aaroncchung/Formula1Data` |
| Branch | `main` |
| Commit reviewed | `4df4f0e` (merge of PR #6) |
| Review date | 2026-10-05 |
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

No repository file was modified during the review other than this document.

### Not verified

- **A refusal from F1's servers on a GitHub runner.** The evidence in AR-13 is
  indirect: one failing log from this project (run 30162384377, 2026-07-25),
  which shows the failure but no HTTP status, a report from another cloud
  platform, and another project's run history.
- **What the R2 bucket currently holds.**
- **Which Cloudflare plan the Pages project is on.** AR-02 assumes Free.
- **Anything rendered in a browser.** Chart and UI defects in AR-12 are
  deduced from code and data.
- **The nine failed runs of 2026-07-05.** Their failing step was tallied, their
  logs were not read.
- **Independent-read reproductions.** The synthetic-input reproductions in
  AR-08 and AR-10 were run by the independent reader, not re-run here.
- **Secondary-source claims in section 5.** OpenF1's price and rate limits, the
  F1TV token requirement for live telemetry, and the coverage of the commercial
  APIs come from documentation summaries or third-party pages, not from tests.
- **Why the committed Monaco result is stale.** See AR-15.

---

## 2. Executive summary

**Recommendation: a major rewrite, scoped to the data plane.** The data plane
is everything between FastF1 and the pixels: how sessions are ingested, how
artifacts are formatted and stored, how they are published, and how a page
loads them. The analysis code and the frontend should be kept and reworked in
place. A restart is not justified.

| Layer | Assessment | Recommended fate |
| --- | --- | --- |
| Cloud ingestion (Worker job queue, D1, Actions workflow, R2 publisher) | Careful code; the system has succeeded in 2 of 118 runs | Replace with one batch job |
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

**Why not incremental patches.** That is what PRs #2 to #6 were, and what the
open PRs #8 to #10 continue. All of that work is on the cloud ingestion path,
which is still at 2 successes in 118 runs and is currently switched off.
Patches cannot remove the four structural causes: two competing data paths
(AR-03), the deploy file cap (AR-02), the artifact format (AR-05) and the
page payload design (AR-07).

### Counts

| Severity | Count | Findings |
| --- | --- | --- |
| Critical | 1 | AR-01 |
| High | 7 | AR-02, AR-03, AR-04, AR-05, AR-08, AR-13, AR-15 |
| Medium | 7 | AR-06, AR-07, AR-09, AR-10, AR-11, AR-12, AR-16 |
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
| Failed at `Process ingestion job` | 11 | 9 on 2026-07-05 (logs not read); 2 on 2026-07-25, where the log read shows FastF1 returning no lap data |
| Failed at `Report ingestion success` | 1 | Success callback, 2026-07-25 |

Related workflows over the same period:

- `Schedule completed session ingestion`: 147 of 148 runs succeeded, but this
  workflow only submits requests to the Worker. It is now `disabled_manually`.
- `Backfill F1 data`: 8 succeeded, 10 failed. It also only submits requests.
- `Warm FastF1 cache`: 2 runs, both failed.

After the bash fix landed, three runs happened (2026-07-25). Two died inside
ingestion and one at the callback. No ingestion run has happened since PR #6
merged on 2026-07-26, so the `queue: max` fix for the cancellations and the
R2 rollback work have never executed in a real run.

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
five more races. A full 2026 season across all session types is 22 meetings
with five sessions each, far beyond either cap. `frontend/public/data` is also
1.2 GB in the working tree and is checked out on every workflow run.

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
| **Status** | Partly addressed by open PR #9 |

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

Publish each generation under a new prefix and flip one pointer object last,
as PR #9 does. Upload through R2's S3-compatible API so that a missing object
is a real 404. With the format change in AR-05, a session becomes about 45
objects and the pacing logic is no longer needed.

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
ingest every completed session that is not yet published. Remove the queue,
the D1 job tables, the dispatch and the callbacks.

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

**Evidence**

The 2026 race pages are 3.0 to 3.6 MB of HTML each. The page loads 20
artifacts at build time, including the 3.7 MB position replay and the 266 KB
telemetry index, and passes them all to one client component. If any of 13
required artifacts fails to load, or the default telemetry comparison does,
the whole page is replaced by an error.

The build can only produce a full page for sessions present in git at build
time. Sessions that arrive later are rendered by a second, client-side route
through `SessionIngestionPanel`. F-04 was a divergence between the two.

**Recommended direction**

A static shell that loads each tab's data from `/data` when the tab opens.
The client loader already exists (`lib/api.ts` with `loadSessionDashboard`),
and the reference branch in PR #7 prototyped the routing.

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
local work: one function each, with no architectural dependency. Pit loss
should be computed from the two pit-stop durations in AR-16, and corner
analysis from the official corner positions in AR-17.

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
- `schema_version` is written into every artifact and never checked.

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

**Impact**

The committed artifacts can be regenerated on one machine only. The loss is
recoverable with `git checkout`, but an unnoticed commit would remove the data
from the site.

**Recommended direction**

Resolved by AR-03: with R2 as the only store, a local build writes to a
scratch directory and publishing is a separate, additive step.

Keep each session's normalised source dataset in R2 as well. Upstream access
has tightened repeatedly: live telemetry moved behind a login in 2025, the
2026 feed carries no aero or ERS data (AR-18), and cloud addresses appear to
have been refused since July 2026 (AR-13). Data that may not be re-fetchable
should not exist on one machine only.

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
| **Confidence** | Medium (three independent signals; no refusal observed directly on a GitHub runner) |
| **Status** | Open; needs one confirming request from a runner |

**Evidence**

- **This project.** In run 30162384377 (2026-07-25), for the 2026 round 1
  race, FastF1 logged `Failed to load timing data!` on each of three attempts
  with a cold cache, and the run ended with
  `FastF1 session.load returned without populated laps`. FastF1 logs no HTTP
  status at that level. Both `Warm FastF1 cache` runs failed the same day.
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

No architecture removes this. It decides where ingestion can run, so it should
be settled first.

**Recommended direction**

Confirm with one request to
`https://livetiming.formula1.com/static/2026/Index.json` from a GitHub-hosted
runner. If it is refused, run the batch command on a self-hosted runner or as
a scheduled task on a local machine; only the place it runs changes. OpenF1
and the TracingInsights archive are hosted independently of F1's archive and
are the fallbacks if neither is acceptable, at the cost described in
section 5.

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
stream on the host FastF1 already reads. Store both durations, and compute pit
loss from the lane time with stops under safety car or red flag excluded
(AR-08).

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
| Jolpica-F1, through `fastf1.ergast` | Final race and sprint classification | The right choice, and under-used (AR-15). Limits are 4 requests a second and 500 an hour. It held the 2026-10-04 race on 2026-10-05. |
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

1. Keep FastF1 as the primary source and run it from a network F1 answers
   (AR-13).
2. Take standings and final classifications from Jolpica, re-fetch recent
   rounds on every run, and ingest sprints (AR-15).
3. Parse `PitStopSeries` for pit stops (AR-16).
4. Use `get_circuit_info()` for corners (AR-17).
5. Drop DRS from 2026 sessions (AR-18).
6. Keep the normalised source datasets in R2 (AR-11).
7. If the live page is built, pay for OpenF1 and use its stream (AR-19).

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

---

## 6. Recommended architecture

### Target

```text
FastF1 + Jolpica ---> one batch command ---> compact artifacts ---> R2 (only store)
                      (scheduled, on a       (typed, generated      new prefix per
                       network F1 answers)    TS types)             publish, pointer
                                                                    flipped last
                                                                         |
browser <--- static shell, loads each tab's data <--- Worker /data ------+
```

### Order of work

1. **Confirm where ingestion can run (AR-13).** Make one request to F1's
   archive from a GitHub-hosted runner. Expect a refusal, and plan for a
   self-hosted runner or a local scheduled task.
2. **New artifact format and typed contract (AR-05, AR-09).** Columnar
   telemetry bundled per driver, minified JSON, integer milliseconds, Pydantic
   models at the write boundary, generated TypeScript types. Add both pit-stop
   durations (AR-16) and the official corner positions (AR-17), and omit DRS
   from 2026 (AR-18).
3. **Publish to R2 only (AR-03, AR-04).** New prefix per generation, pointer
   flipped last, uploads through the S3-compatible API. Store each session's
   normalised source dataset alongside it (AR-11). Carry over the pointer and
   resolver design from PR #9 and the contract-fixture idea from PR #10.
4. **One batch command on a schedule (AR-06, AR-10).** Remove the queue, the
   D1 job tables, the dispatch, the callbacks, the scheduler module and the
   FastAPI shell. Move the Python code into one package. Ingest sprints, take
   standings from Jolpica and re-fetch recent classifications on every run
   (AR-15).
5. **Runtime loading per tab (AR-07, AR-02, AR-11).** Remove real session data
   from git and from the deploy. The build then needs only the schedule.
6. **Product quality (AR-08, AR-12).** Fix the analysis methods against a
   real-session fixture, fix the charts, and decide the scope of the
   placeholder pages.

Steps 2 to 5 are one rewrite and should not be shipped piecemeal against the
old paths. Step 6 is independent of them and can proceed in parallel.

### Size

About 4,050 lines are removed outright: the scheduler, four workflows, the
Worker's repository and session-status modules with their tests, the
migrations, the API-only backend code and the ingestion panel. A further 3,900
lines (`local_queue_worker.py`, its tests and `worker/src/index.mjs`) are
replaced by much smaller code. That is roughly 7,000 of 18,500 tracked source
lines. This is an estimate from file sizes, not a plan-level count.

---

## 7. Pull requests and issues

The repository has no GitHub issues, open or closed. At the time of the review
there were four open pull requests, all opened on 2026-07-27 and all on the
cloud ingestion path.

| PR | Content | Relation to this plan | Status |
| --- | --- | --- | --- |
| #7 (draft, conflicting) | Reference-only branch from 2026-07-13: generation-prefixed publishing, an R2-only source, and a runtime-fetching frontend shell | Its frontend shell and R2-only source were recorded as "deliberately not being taken". This plan takes them (steps 3 and 5), so the branch is prior art for the rewrite. | Open, kept as reference |
| #8 | Guard against a stale status poll in `SessionIngestionPanel`; adds a frontend test runner to CI | The panel is removed if browser-requested ingestion is dropped. The test runner and the request guard are independent of the plan and worth keeping. | Open |
| #9 | Immutable generations with a pointer flip; deletes about 450 lines of rollback code | The layout and the Worker key resolver are the design step 3 adopts. The publisher half is still built on `wrangler` and the callback contract, both of which step 3 and step 4 replace. Its description records that its first commit shipped a data-loss bug in generation pruning. | Closed 2026-10-05 as superseded |
| #10 (stacked on #9) | Seeds D1 session status from R2; publisher and Worker contract fixture; pins newlines in `write_json` | The D1 seeding is removed by step 4. The contract fixture and the newline fix should be carried over. | Closed 2026-10-05 as superseded |

The branches of #9 and #10 (`feat/immutable-artifact-generations`,
`feat/session-status-r2-seed`) were left in place. From them the rewrite should
carry over:

- `createR2KeyResolver` and the absent-versus-unreadable pointer handling in
  `worker/src/artifact-store.mjs`.
- The `active.json` pointer and generation layout, and the pruning guards.
- `docs/r2-generation-validation.md` as the checklist for the first real
  publish.
- The publisher and Worker contract test with its committed fixture.
- The `newline="\n"` pin in `write_json` and the `.gitattributes` rule.

---

## 8. Decisions needed

1. **Browser-requested ingestion.** Step 4 removes it. It works only behind
   Cloudflare Access, and a scheduled job that ingests every completed session
   makes it unnecessary. If it is wanted, a thin Worker endpoint that triggers
   the workflow directly would serve, without the queue or D1.
2. **Where ingestion runs.** If step 1 confirms the refusal, the choice is
   between a self-hosted GitHub runner, which keeps the workflow interface, and
   a scheduled task on a local machine, which is simpler. Either needs a
   machine that is on when sessions finish.
3. **PR #8.** Its fate follows from decision 1. If the ingestion panel goes,
   salvage the test runner and the request guard and close the rest; if it
   stays, merge it.
4. **Scope of live timing and the placeholder pages.** `/live` and `/settings`
   are stubs today; either build them or remove them from the navigation. Live
   timing needs a paid OpenF1 account (AR-19).
