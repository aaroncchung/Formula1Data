# Formula 1 Data

Formula 1 Data is a static-first Formula 1 analytics dashboard. Cloudflare Pages serves a Next.js static route shell, while production views read the current historical catalog and session artifacts from the Worker `/data/*` boundary backed by R2. Local/offline builds use the same schemas from `frontend/public/data`. FastF1, pandas, and other heavy Python work remain outside Cloudflare Workers.

This project is unofficial and is not associated with Formula 1, FIA, FastF1, or OpenF1.

## Features

- Dark, dense motorsport analytics UI with sidebar navigation and session tabs.
- Historical session dashboard for overview, lap times, race pace, strategy, telemetry, position replay, weather, race control, and results.
- Global season/event/session navigation with artifact-backed driver and lap selectors.
- Every usable FastF1 telemetry lap retained at a browser-safe maximum of 300 samples per lap.
- Track-dominance minisectors, inferred corner and braking analysis, car/team performance profiles, and practice long-run pace predictions.
- Fuel-adjusted tyre degradation with robust outlier filtering and explicit model assumptions.
- Driver and constructor standings, ideal-lap potential, team-mate comparison, and pit-lane transit analysis.
- Local/offline JSON artifacts under `frontend/public/data`.
- Python pipeline for sample generation, FastF1 ingestion, and precomputed analysis.
- Cloudflare Pages-ready static export from `frontend/out`.
- Cloudflare Worker API for R2 artifact reads, D1 status/catalog tables, Queue-backed ingestion requests, and OpenF1 live proxying.
- Optional FastAPI backend retained for local development experiments, but not required for the Cloudflare production request path.

## Architecture

```text
frontend/ Next.js static route shells --------> Cloudflare Pages
                  | browser runtime reads
                  v
         Cloudflare Worker /data/* ------------> R2 artifacts

backend/data ----> pipeline/ ----> verified R2 generation + active pointer
sample + FastF1    ingest + precompute
```

Core rule: production HTML, JS, and CSS remain static, but historical JSON is runtime data served by the Worker from R2. Python, FastF1, pandas, pyarrow, and local disks remain ingestion-runner concerns only. Running the frontend without Worker variables keeps the fully static `/data` offline mode.

Runtime catalog links use the always-exported `/seasons/explore` route with year, round, and session query parameters, so newly published catalog entries do not require another Pages build. Pretty `/seasons/{year}/{round}/{session}` routes generated from the checked-in catalog remain available for existing bookmarks.

Hybrid production mode adds this path:

```text
frontend static export ------> Cloudflare Pages
        | runtime /data/* and /api/*
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
│   ├── src/lib/api.ts        Browser runtime artifact reader
│   ├── src/lib/route-catalog.ts Build-time route-shell catalog reader
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

`catalog.json`, season files, session manifests, and telemetry indexes retain schema version 1. Telemetry is downsampled to at most 300 samples per driver/lap artifact by default. R2 additionally stores a versioned session generation and a small `sessions/{session_id}/active.json` pointer; the Worker resolves the existing public session paths through that pointer.

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

Set `NEXT_PUBLIC_DYNAMIC_API_BASE_URL=http://localhost:8787` if the frontend should call the local Worker directly for live/status/queue APIs. Leave it empty for static-only browsing.

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

## Pipeline Commands

Offline sample artifacts:

```powershell
python -m pipeline generate --sample
```

Build artifacts from all processed datasets under `backend/data/processed`:

```powershell
python -m pipeline build-artifacts
```

Ingest one FastF1 session and rebuild only that session plus its catalog and season indexes:

```powershell
python -m pipeline ingest-session --year 2025 --event "Monaco Grand Prix" --session R
```

Ingest all available FastF1 sessions for a season and rebuild only that season's processed sessions plus shared indexes:

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

For local/offline data, install the backend dependencies and run
`python -m pipeline ingest-session --year <year> --event "<event name>" --session <code>`.
Review the changed session and indexes under `frontend/public/data`; use `--force` to replace an
existing processed session.

Production ingestion must use the Worker/Queue runner described below. Its verified R2 publication
is visible immediately through `/seasons/explore` and does not require committing generated data or rebuilding Pages.

## Cloudflare Hybrid Mode

For a complete production checklist, see
[`docs/production-ingestion-setup.md`](docs/production-ingestion-setup.md).

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

Status checks require both a D1 `ready` state and the active session manifest. A manifest uploaded before verification cannot make a session ready. Trusted canonical manifests from the initial R2 seed are registered lazily when first checked, but fallback files and versioned generations cannot bypass the verified callback. Missing sessions can be queued from the frontend; the Worker creates or reuses an active `ingest_session` job, writes D1 state, and sends the Cloudflare Queue message.

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

R2 publication is incremental and generation-safe. The runner downloads the current catalog and
affected season index, builds only the affected session in a temporary directory, uploads it under
`sessions/{session_id}/generations/{manifest_sha256}/`, and verifies every manifest-referenced
object's size and SHA-256 checksum. It then atomically switches `active.json` and publishes the
season index and catalog last. A failed refresh leaves the previous active generation readable.
Before accepting the success callback, the Worker independently verifies that `active.json` points
to the callback's manifest and that the active manifest's size and SHA-256 checksum match. It does
not re-read every section already verified by the runner. Normalized datasets remain private under
`source/`.
Keep direct R2 public access disabled; the Worker allowlist is the intended read boundary.

The current R2 `catalog.json` must exist before queue-driven ingestion begins. Seed the complete
historical artifact tree during migration so R2 is the single production source of truth; Pages
files remain the local/offline source only. Requiring the current catalog prevents a transient R2
or credential failure from replacing production indexes with a partial local view.

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

No frontend secret is required. For production, set `NEXT_PUBLIC_ARTIFACT_BASE_URL` to the Worker `/data` URL and `NEXT_PUBLIC_DYNAMIC_API_BASE_URL` to the Worker origin at build time. The GitHub Pages workflow reads both from repository variables.

If `NEXT_PUBLIC_ARTIFACT_BASE_URL` is omitted, it derives from `NEXT_PUBLIC_DYNAMIC_API_BASE_URL`; if both are omitted, the frontend uses same-origin `/data` for local/offline static files. Production should not configure the Pages artifact fallback after the R2 migration is complete.

Deployment options:

- Cloudflare Pages Git integration: connect the repo, use the settings above, and let Pages build from `frontend`.
- Manual GitHub Actions deploy: run `.github/workflows/cloudflare-pages.yml` with repository secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and `CLOUDFLARE_PAGES_PROJECT_NAME`.

`frontend/wrangler.jsonc` also declares `pages_build_output_dir: ./out` for direct Wrangler deploys.

## GitHub Actions

- `frontend-ci.yml`: generates sample artifacts, runs frontend lint, builds the static export, and uploads `frontend/out`.
- `generate-artifacts.yml`: manually generates local/offline artifacts or validates sample generation. An optional data commit updates the offline snapshot only; production reads R2.
- `cloudflare-pages.yml`: manual static export deployment to Cloudflare Pages via Wrangler.

## Artifact Size Strategy

- Catalog and season files stay small and route-oriented.
- Session data is split by section so a page can fetch only what it needs.
- Analysis artifacts are precomputed once in the pipeline instead of calculated per browser request.
- Telemetry is split by driver/lap and capped at 300 samples per lap artifact.
- Queue-driven R2 uploads update only a new session generation, its active pointer, the affected season, and the catalog.
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

