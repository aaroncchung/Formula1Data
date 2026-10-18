# The old data path

This was the repository's README until the data plane was rewritten. It
describes the path the rewrite replaces: `pipeline/`, the FastAPI backend, the
Worker in `worker/src/index.mjs` with its D1 tables and queue, and the
ingestion workflows. All of that is still in the tree and is still what `main`
deploys until the rewrite is merged; the plan removes it once the new path has
carried three race weekends unattended (`architecture-review-findings.md`,
section 6, step 6). The site on the rewrite branch reads none of it, and
`frontend/public/data`, which this text refers to throughout, is no longer in
the tree. For how things work now, see the README and `data-plane.md`.

What follows is unchanged, and paths in it are from the repository root.

Formula 1 Data is a static-first Formula 1 analytics dashboard. The production app is a Next.js static export that reads precomputed JSON artifacts from `/data`. The project also includes a Cloudflare-native dynamic data plane for on-demand session ingestion and live-session proxying while keeping FastF1, pandas, and other heavy Python work outside Cloudflare Workers.

This project is unofficial and is not associated with Formula 1, FIA, FastF1, or OpenF1.

## Features

- Dark, dense motorsport analytics UI with sidebar navigation and session tabs.
- Historical session dashboard for overview, lap times, race pace, strategy, telemetry, position replay, weather, race control, and results.
- Global season/event/session navigation with artifact-backed driver and lap selectors.
- Every usable FastF1 telemetry lap retained at a browser-safe maximum of 300 samples per lap.
- Track-dominance minisectors, inferred corner and braking analysis, car/team performance profiles, and practice long-run pace predictions.
- Fuel-adjusted tyre degradation with robust outlier filtering and explicit model assumptions.
- Driver and constructor standings, ideal-lap potential, team-mate comparison, and pit-lane transit analysis.
- Static JSON artifacts committed under `frontend/public/data`.
- Python pipeline for sample generation, FastF1 ingestion, and precomputed analysis.
- Cloudflare Pages-ready static export from `frontend/out`.
- Cloudflare Worker API for R2 artifact reads, D1 status/catalog tables, Queue-backed ingestion requests, and OpenF1 live proxying.
- Optional FastAPI backend retained for local development experiments, but not required for the Cloudflare production request path.

## Architecture

```text
                 manual or scheduled
                 GitHub Actions / local CLI
                         |
                         v
backend/data ----> pipeline/ ------------------+
sample + FastF1    ingest + precompute         |
processed JSON                                  v
                                       frontend/public/data/
                                       split static JSON
                                                |
                                                v
frontend/ Next.js static export ------> Cloudflare Pages
Recharts dashboard                      any device, no backend
```

Core rule: deployed historical browsing serves static HTML, JS, CSS, and JSON. Dynamic requests go through the Cloudflare Worker, but Python, FastF1, pandas, pyarrow, and local disks remain ingestion-runner concerns only.

Hybrid production mode adds this path:

```text
frontend static export ------> Cloudflare Pages
        |                               |
        | /data/*, /api/*               v
        +----------------------> Cloudflare Worker
                                  | R2: JSON artifacts
                                  | D1: sessions, jobs, manifests
                                  | Queues: ingestion requests
                                  v
                         external Python ingestion runner
                         FastF1 + pipeline + optional R2 upload
```

## File Tree

```text
.
├── pipeline/                 Python ingestion and artifact generation CLI
│   └── analysis/             Dependency-light precomputed analytics
├── frontend/
│   ├── public/data/          Generated static JSON artifacts
│   ├── src/lib/api.ts        Browser static artifact reader
│   ├── src/lib/published/    Runtime reader of published data (R2, through the read-only Worker)
│   └── next.config.ts        Static export configuration
├── backend/                  Optional local FastAPI/FastF1 code path
│   ├── app/                  Existing routes, ingestion, services, models
│   └── data/processed/       Source datasets for the pipeline
├── worker/                   Cloudflare Worker API and focused tests
├── migrations/               Cloudflare D1 schema migrations
└── .github/workflows/        CI, artifact generation, Cloudflare deploy
```

## Static Artifacts

Artifacts are split to keep browser requests bounded:

```text
frontend/public/data/catalog.json
frontend/public/data/seasons/{year}.json
frontend/public/data/sessions/{session_id}/summary.json
frontend/public/data/sessions/{session_id}/drivers.json
frontend/public/data/sessions/{session_id}/laps.json
frontend/public/data/sessions/{session_id}/results.json
frontend/public/data/sessions/{session_id}/stints.json
frontend/public/data/sessions/{session_id}/pit-stops.json
frontend/public/data/sessions/{session_id}/weather.json
frontend/public/data/sessions/{session_id}/race-control.json
frontend/public/data/sessions/{session_id}/analysis/lap-times.json
frontend/public/data/sessions/{session_id}/analysis/race-pace.json
frontend/public/data/sessions/{session_id}/analysis/tyre-degradation.json
frontend/public/data/sessions/{session_id}/analysis/strategy.json
frontend/public/data/sessions/{session_id}/analysis/ideal-laps.json
frontend/public/data/sessions/{session_id}/analysis/team-mate-comparison.json
frontend/public/data/sessions/{session_id}/analysis/track-dominance.json
frontend/public/data/sessions/{session_id}/analysis/corner-analysis.json
frontend/public/data/sessions/{session_id}/analysis/car-performance.json
frontend/public/data/sessions/{session_id}/analysis/pace-prediction.json
frontend/public/data/sessions/{session_id}/telemetry/index.json
frontend/public/data/sessions/{session_id}/telemetry/{driver_code}-lap-{lap_number}.json
frontend/public/data/sessions/{session_id}/position-replay.json
```

`catalog.json`, season files, session manifests, and telemetry indexes include schema version, generation timestamp, source files, and size metadata. Telemetry is downsampled to at most 300 samples per driver/lap artifact by default.

## Local Development

From the repo root:

```powershell
python -m pipeline generate --sample
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The dev server reads the same `/data/...` paths that production uses.

Optional local Worker development does not require real Cloudflare credentials. In one terminal run the frontend, and in another run Wrangler local dev:

```powershell
cd frontend
npm run dev
```

```powershell
npx wrangler dev
```

For local Worker artifact fallback, set this in your shell or `.dev.vars`:

```text
STATIC_DATA_BASE_URL=http://localhost:3000/data
```

Static export:

```powershell
python -m pipeline generate --sample
cd frontend
npm run lint
npm run build
```

The Cloudflare Pages output directory is `frontend/out`.

### Tests

Two suites, both run by `tests.yml` in CI. Run them from the repo root:

```powershell
python -m pip install -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

```powershell
node --test "worker/tests/*.test.mjs"
```

The Python suite covers the pipeline, the ingestion normalizer, and the local
queue worker; `backend/tests/conftest.py` puts the repo root and `backend/` on
`sys.path`, so individual files can be run on their own. The Worker suite is
plain `node:test` with no dependencies to install. `repository-d1.test.mjs`
exercises the real D1 SQL against `node:sqlite` with `migrations/` applied, and
skips itself on Node versions where that module is still flagged (Node 22 needs
`--experimental-sqlite`; Node 24 does not).

## Pipeline Commands

Offline sample artifacts:

```powershell
python -m pipeline generate --sample
```

Build artifacts from all processed datasets under `backend/data/processed`:

```powershell
python -m pipeline build-artifacts
```

Ingest one FastF1 session and rebuild static artifacts:

```powershell
python -m pipeline ingest-session --year 2025 --event "Monaco Grand Prix" --session R
```

Ingest all available FastF1 sessions for a season:

```powershell
python -m pipeline ingest-season --year 2025
```

Preserve the original race-only workflow:

```powershell
python -m pipeline ingest-season --year 2025 --races-only
```

Limit ingestion to selected session codes:

```powershell
python -m pipeline ingest-season --year 2025 --sessions FP1 Q R
```

Plan a historical backfill without writing data:

```powershell
python -m pipeline backfill --years 2025 2026 --dry-run
```

Backfill completed race sessions for 2025 and 2026, skipping future sessions and already processed sessions:

```powershell
python -m pipeline backfill --years 2025 2026 --races-only
```

The local `backfill` command remains useful for offline artifact generation. The production
`Backfill F1 data` GitHub workflow instead submits each candidate through the Worker API so D1,
Queues, job callbacks, R2 publication, and retry behavior remain consistent with browser-triggered
ingestion.

Backfill all completed sessions FastF1 can load:

```powershell
python -m pipeline backfill --years 2025 2026
```

Use `--through-date YYYY-MM-DD` to pin the latest session date, `--sessions FP1 Q R` to limit session types, and `--force` to replace existing processed sessions. Review generated files under `backend/data/processed` and `frontend/public/data`; `backend/data/processed/seasons` and `backend/data/processed/sessions` are ignored by default, while committed `frontend/public/data` artifacts can be reused by the ingestion workflow without calling FastF1 again.

For the current 2026 season, this writes the full FastF1 schedule and ingests every available session FastF1 can load:

```powershell
python -m pipeline ingest-season --year 2026
```

Unavailable future sessions are skipped during ingestion but remain visible as scheduled meetings in the season catalog.

FastF1 ingestion needs backend dependencies:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
cd ..
python -m pipeline ingest-session --year 2025 --event "Monaco Grand Prix" --session R
```

Race and sprint ingestion refreshes the final classification from FastF1's Jolpica interface with
the HTTP cache disabled. Publication fails if the classification is unavailable, has invalid or
duplicate positions, or is missing status, points, grid, or lap counts.

Sample generation does not require network access or backend dependencies.

## Adding A Race Or Session

1. Install backend dependencies if you have not already.
2. Run `python -m pipeline ingest-session --year <year> --event "<event name>" --session <code>`.
3. Review generated files under `frontend/public/data`.
4. Run `cd frontend; npm run lint; npm run build`.
5. Commit the updated `frontend/public/data` artifacts.

Use `--force` if you need to replace an existing processed session.

## Cloudflare Hybrid Mode

For a complete production checklist, see
[`docs/production-ingestion-setup.md`](production-ingestion-setup.md).

The root `wrangler.jsonc` defines the API Worker. `frontend/wrangler.jsonc` remains the Cloudflare Pages static export config.

Bindings:

- R2 bucket binding: `ARTIFACTS_BUCKET`
- D1 database binding: `F1_DB`
- Queue producer binding: `INGESTION_QUEUE`
- Queue consumer: `f1-ingestion-jobs`

Create resources, then replace the placeholder D1 `database_id` in `wrangler.jsonc`:

```powershell
npx wrangler r2 bucket create formula-1-data-artifacts
npx wrangler r2 bucket create formula-1-data-artifacts-dev
npx wrangler d1 create formula-1-data
npx wrangler queues create f1-ingestion-jobs
npx wrangler d1 migrations apply formula-1-data --local
npx wrangler d1 migrations apply formula-1-data --remote
```

Worker variables and secrets:

```text
ENABLE_LIVE_MODE=false
OPENF1_BASE_URL=https://api.openf1.org/v1
STATIC_DATA_BASE_URL=
CORS_ALLOW_ORIGIN=https://your-pages-site.pages.dev
INGESTION_WEBHOOK_URL=https://your-python-runner.example.com/jobs
REQUIRE_INGESTION_REQUEST_AUTH=false
```

Set secrets instead of committing them:

```powershell
npx wrangler secret put OPENF1_API_KEY
npx wrangler secret put INGESTION_WEBHOOK_TOKEN
npx wrangler secret put INGESTION_API_TOKEN
```

`OPENF1_API_KEY`, `INGESTION_WEBHOOK_TOKEN`, and `INGESTION_API_TOKEN` must never be exposed through `NEXT_PUBLIC_*` variables.

### Personal access protection

The browser-compatible `POST /api/ingestion/session` route cannot safely embed a secret. Protect the Pages site and Worker custom domain with Cloudflare Access, restricted to your identity, while leaving `REQUIRE_INGESTION_REQUEST_AUTH=false`. If only trusted non-browser clients request ingestion, set the variable to `true` and send `INGESTION_API_TOKEN` as a bearer token. Do not leave the browser-compatible ingestion route exposed on an unprotected `workers.dev` domain.

## On-Demand Ingestion Flow

The Worker exposes:

- `GET /api/session-status?year=&round=&session=`
- `POST /api/ingestion/session`
- `GET /api/ingestion/jobs/:jobId`
- `POST /api/ingestion/jobs/:jobId/status`
- `GET /data/*`

Status checks look for `sessions/{session_id}/manifest.json` or `summary.json` in R2, then D1 active jobs. Missing sessions can be queued from the frontend. The Worker creates or reuses an active `ingest_session` job, writes D1 state, and sends the Cloudflare Queue message.

Queue message shape:

```json
{
  "version": 1,
  "job_id": "ingest_session:2026-08-r:...",
  "kind": "ingest_session",
  "session_id": "2026-08-r",
  "year": 2026,
  "round": 8,
  "session": "R",
  "meeting_id": "2026-08-monaco-grand-prix",
  "meeting_name": "Monaco Grand Prix",
  "artifact_base_path": "sessions/2026-08-r",
  "force": false,
  "requested_at": "2026-07-04T12:00:00.000Z"
}
```

For local simulation, save a message as JSON or JSONL and run:

```powershell
python -m pipeline process-queue --message-file .\message.json
```

To report status back to a local Worker:

```powershell
python -m pipeline process-queue --message-file .\message.json --callback-url http://localhost:8787 --callback-token <token>
```

Set `INGESTION_API_TOKEN=<token>` for the Worker, or set `ALLOW_UNAUTHENTICATED_INGESTION_CALLBACKS=true` only for local throwaway testing.

To upload generated artifacts to R2 from an external runner with Wrangler credentials:

```powershell
python -m pipeline process-queue --message-file .\message.json --artifact-destination r2 --r2-bucket formula-1-data-artifacts
```

Production queue consumption is intentionally a boundary: the Worker consumer can dispatch messages to `INGESTION_WEBHOOK_URL`, and the external Python runner performs FastF1 ingestion, artifact generation, optional R2 upload, then calls the protected job-status callback.

R2 publication is incremental. The runner first downloads the current R2 catalog and affected
season index, builds in a temporary directory, merges the new session, uploads the normalized
source dataset under `source/sessions/{session_id}/dataset.json`, and publishes session files,
manifest, season index, then catalog in that order. The Worker only exposes `catalog.json`,
`seasons/*`, and `sessions/*` through `/data`, so normalized source datasets remain private.
Keep direct R2 public access disabled; the Worker allowlist is the intended read boundary.

The current R2 `catalog.json` must be readable before queue-driven ingestion publishes anything, and
a run that cannot read it fails. Wrangler exits non-zero for both "no such object" and "that read
failed", so tolerating an unreadable catalog would let one transient failure republish an index
containing only the session just ingested, hiding every other session from clients. The download is
retried with backoff first; a persistent failure is then an error rather than a guess.

Seed the initial catalog and season files from `frontend/public/data` during first deployment (see
`docs/production-ingestion-setup.md`, section 5). If instead you want the first ingestion itself to
create the indexes in a genuinely empty bucket, pass `--allow-missing-catalog` for that one run:

```powershell
python -m pipeline process-queue --message-file .\message.json --artifact-destination r2 --r2-bucket formula-1-data-artifacts --allow-missing-catalog
```

That flag is for bootstrap only. Leave it off everywhere else, including the ingestion workflow: on a
bucket that already has a catalog it converts a failed read into a silent index overwrite.

### Scheduling and recovery

`schedule-ingestion.yml` runs hourly and submits recently completed sessions through the same
Worker endpoint. `backfill-data.yml` uses the same scheduler for explicit historical years. Configure
these GitHub values:

```text
Variable: WORKER_BASE_URL
Secret: INGESTION_API_TOKEN
Optional Access secrets: CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET
```

The Worker checks every 30 minutes for jobs that have remained queued or running for more than
`STALE_JOB_TIMEOUT_MINUTES` and marks them failed so they can be retried. Exhausted Queue messages
are retained in `f1-ingestion-jobs-dlq`.

## Live Data

The live page now polls Worker routes under `/api/live/*`. The Worker proxies OpenF1 server-side and caches responses for about 3 seconds. Live mode degrades to a disabled payload unless `ENABLE_LIVE_MODE=true`. Upstream OpenF1 failures return a graceful disabled/error-shaped payload and the browser retries on the next poll.

The browser never calls OpenF1 directly and never receives `OPENF1_API_KEY`.

## Backend Endpoint Roles

Historical read endpoints are now static artifacts:

- Seasons, meetings, sessions, summary, drivers, laps, results, stints, pit stops, weather, and race control.
- Race pace, lap times, fuel-adjusted tyre degradation, strategy, ideal laps, team-mate comparison, telemetry comparison, position replay, track dominance, corner analysis, car performance, and practice pace prediction.

Runtime behavior remains outside the production path:

- Ingestion endpoints and scripts perform network/build-time work.
- OpenF1 live endpoints are proxied by the Worker when live mode is enabled, and resolve to a disabled payload otherwise.
- FastAPI can still be useful for local experimentation, but the Cloudflare production path does not require it.

## Cloudflare Pages

Recommended Pages settings:

```text
Root directory: frontend
Build command: npm ci && npm run build
Build output directory: out
Node version: 22
```

No frontend secret is required for historical mode.

For hybrid mode, configure `/api/*` and `/data/*` to reach the Worker. Static-only deployments can continue serving committed `frontend/public/data` directly from Pages.

Deployment options:

- Cloudflare Pages Git integration: connect the repo, use the settings above, and let Pages build from `frontend`.
- Manual GitHub Actions deploy: run `.github/workflows/cloudflare-pages.yml` with repository secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and `CLOUDFLARE_PAGES_PROJECT_NAME`.

`frontend/wrangler.jsonc` also declares `pages_build_output_dir: ./out` for direct Wrangler deploys.

## GitHub Actions

- `tests.yml`: runs the Python suite (`pytest backend/tests`) and the Cloudflare Worker suite (`node --test`) on every pull request and push to `main`.
- `frontend-ci.yml`: generates sample artifacts, runs frontend lint, builds the static export, and uploads `frontend/out`.
- `generate-artifacts.yml`: manually generates sample artifacts, ingests one FastF1 session, or ingests sessions for a full FastF1 season; scheduled runs validate sample artifact generation weekly. Manual runs can optionally commit `frontend/public/data`.
- `cloudflare-pages.yml`: manual static export deployment to Cloudflare Pages via Wrangler.

## Artifact Size Strategy

- Catalog and season files stay small and route-oriented.
- Session data is split by section so a page can fetch only what it needs.
- Analysis artifacts are precomputed once in the pipeline instead of calculated per browser request.
- Telemetry is split by driver/lap and capped at 300 samples per lap artifact.
- Queue-driven R2 uploads update only the catalog, affected season, and affected session rather than re-uploading historical data.
- Heavy raw/cache files stay under `backend/data` and are not part of the static frontend.

## Docker

Docker Compose is no longer the production deployment model. Keep Docker only for local backend or pipeline experimentation if useful. Cloudflare Pages production deploys the static frontend alone.

## Known Limitations

- The committed sample data is synthetic and intentionally small.
- Previously generated sessions must be re-ingested to gain every-lap telemetry and the new advanced analysis artifacts; the code does not invent missing historical telemetry.
- FastF1 ingestion depends on network access and upstream availability. In-progress seasons may only have completed sessions available.
- Telemetry artifacts are downsampled for browser performance.
- Pit duration is total pit-lane transit from FastF1 pit-in to pit-out timing, not stationary service time.
- Pit loss, undercut/overcut, fuel correction, inferred corners, and practice pace predictions are transparent estimates with caveats in each artifact.
- Live OpenF1 support requires Worker live mode and upstream OpenF1 availability.
- Local Worker development can mock Queue/R2/D1 behavior, but production R2 uploads and remote D1 migrations require Cloudflare credentials.

