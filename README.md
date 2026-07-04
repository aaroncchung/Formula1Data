# Formula 1 Data

Formula 1 Data is a static-first Formula 1 analytics dashboard. The production app is a Next.js static export that reads precomputed JSON artifacts from `/data`, so normal historical browsing does not need FastAPI, pandas, pyarrow, FastF1, persistent disks, databases, object storage, or a Python container.

This project is unofficial and is not associated with Formula 1, FIA, FastF1, or OpenF1.

## Features

- Dark, dense motorsport analytics UI with sidebar navigation and session tabs.
- Historical session dashboard for overview, lap times, race pace, strategy, telemetry, position replay, weather, race control, and results.
- Static JSON artifacts committed under `frontend/public/data`.
- Python pipeline for sample generation, FastF1 ingestion, and precomputed analysis.
- Cloudflare Pages-ready static export from `frontend/out`.
- Optional FastAPI backend retained for local development and future live experiments, but removed from the production request path.

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

Core rule: deployed historical browsing only serves static HTML, JS, CSS, and JSON. Python, FastF1, pandas, pyarrow, FastAPI, and local disks are build/ingestion concerns only.

## File Tree

```text
.
├── pipeline/                 Python ingestion and artifact generation CLI
│   └── analysis/             Dependency-light precomputed analytics
├── frontend/
│   ├── public/data/          Generated static JSON artifacts
│   ├── src/lib/api.ts        Browser static artifact reader
│   ├── src/lib/api-server.ts Build-time static artifact reader
│   └── next.config.ts        Static export configuration
├── backend/                  Optional local FastAPI/FastF1 code path
│   ├── app/                  Existing routes, ingestion, services, models
│   └── data/processed/       Source datasets for the pipeline
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

Ingest one FastF1 session and rebuild static artifacts:

```powershell
python -m pipeline ingest-session --year 2025 --event "Monaco Grand Prix" --session R
```

Ingest race sessions for a season:

```powershell
python -m pipeline ingest-season --year 2025
```

For the current 2026 season, this writes the full FastF1 schedule and ingests every race session FastF1 can load:

```powershell
python -m pipeline ingest-season --year 2026
```

Unavailable future races are skipped during ingestion but remain visible as scheduled meetings in the season catalog.

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

Sample generation does not require network access or backend dependencies.

## Adding A Race Or Session

1. Install backend dependencies if you have not already.
2. Run `python -m pipeline ingest-session --year <year> --event "<event name>" --session <code>`.
3. Review generated files under `frontend/public/data`.
4. Run `cd frontend; npm run lint; npm run build`.
5. Commit the updated `frontend/public/data` artifacts.

Use `--force` if you need to replace an existing processed session.

## Backend Endpoint Roles

Historical read endpoints are now static artifacts:

- Seasons, meetings, sessions, summary, drivers, laps, results, stints, pit stops, weather, and race control.
- Race pace, lap times, tyre degradation, strategy, ideal laps, team-mate comparison, telemetry comparison, and position replay.

Runtime behavior remains outside the production path:

- Ingestion endpoints and scripts perform network/build-time work.
- OpenF1 live endpoints are optional future work and currently resolve to a disabled static message in the frontend.
- FastAPI can still be useful for local experimentation, but Cloudflare Pages does not need it.

## Cloudflare Pages

Recommended Pages settings:

```text
Root directory: frontend
Build command: npm ci && npm run build
Build output directory: out
Node version: 22
```

No frontend secret is required for historical mode. `NEXT_PUBLIC_STATIC_DATA_BASE_PATH` defaults to `/data`; only set it if static JSON is served from a different path.

Deployment options:

- Cloudflare Pages Git integration: connect the repo, use the settings above, and let Pages build from `frontend`.
- Manual GitHub Actions deploy: run `.github/workflows/cloudflare-pages.yml` with repository secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and `CLOUDFLARE_PAGES_PROJECT_NAME`.

`frontend/wrangler.jsonc` also declares `pages_build_output_dir: ./out` for direct Wrangler deploys.

## GitHub Actions

- `frontend-ci.yml`: generates sample artifacts, runs frontend lint, builds the static export, and uploads `frontend/out`.
- `generate-artifacts.yml`: manually generates sample artifacts, ingests one FastF1 session, or ingests race sessions for a full FastF1 season; scheduled runs validate sample artifact generation weekly. Manual runs can optionally commit `frontend/public/data`.
- `cloudflare-pages.yml`: manual static export deployment to Cloudflare Pages via Wrangler.

## Artifact Size Strategy

- Catalog and season files stay small and route-oriented.
- Session data is split by section so a page can fetch only what it needs.
- Analysis artifacts are precomputed once in the pipeline instead of calculated per browser request.
- Telemetry is split by driver/lap and capped at 300 samples per lap artifact.
- Heavy raw/cache files stay under `backend/data` and are not part of the static frontend.

## Docker

Docker Compose is no longer the production deployment model. Keep Docker only for local backend or pipeline experimentation if useful. Cloudflare Pages production deploys the static frontend alone.

## Known Limitations

- The committed sample data is synthetic and intentionally small.
- FastF1 ingestion depends on network access and upstream availability. In-progress seasons may only have completed race sessions available.
- Telemetry artifacts are downsampled for browser performance.
- Pit loss and undercut/overcut values are simple estimates.
- Live OpenF1 support is not required for historical browsing and is left as future serverless work.

