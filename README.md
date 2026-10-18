# Formula 1 Data

A Formula 1 analytics site: every race and sprint of the season, with lap
times, race pace, strategy, telemetry, a replay of positions on track, weather,
race control and results, and the season's standings.

This project is unofficial and is not associated with Formula 1, the FIA,
FastF1, Jolpica or MultiViewer.

## How it is put together

```text
F1 archive --> fetch -----------> source archive --> build ----------> R2
               (a machine F1      in R2              (any machine;     generation per publish,
                answers)          one snapshot       never asks F1)    pointer written last
                                  per fetch                                 |
Jolpica ----------------------------------------------^                    |
                                                                            |
browser <--- static site, pages load at runtime <--- read-only Worker ------+
```

- **Fetch** copies a session from F1's timing archive into an archive in
  Cloudflare R2, as FastF1's cache of it. It is made to run as a scheduled
  task on a machine at home, because F1 refuses GitHub's hosted runners. The
  task is not registered yet: until it is, sessions are fetched by hand.
- **Build** turns an archived session into typed JSON files and publishes them
  to R2 as a generation that is never changed afterwards, with a pointer to it
  written last. It asks nothing of F1 and runs on hosted runners.
- A **read-only Worker** serves what was published.
- The **site** is a Next.js static export on Cloudflare Pages. It holds no
  data: every page loads what it shows from the Worker when it is opened.

A session is published as complete only when every feed arrived and every
measure of its coverage is met; one that falls short is fetched again, and
published as partial, saying what it lacks, once waiting longer will not help.

[`docs/data-plane.md`](docs/data-plane.md) says how to run all of this: the
commands, the credentials, setting a machine up, the scheduled task, and how to
check a publication.
[`docs/architecture-review-findings.md`](docs/architecture-review-findings.md)
is the review this design came out of. Its section 6 is the plan and its
section 10 says where each step of it stands.

## What is in the repository

| Path | What it is |
| --- | --- |
| `f1data/` | The data plane, one Python package: fetch, archive, build, publish, and the command line (`python -m f1data`) |
| `backend/app/analysis/` | The analyses the build runs: race pace, strategy, ideal laps, team-mate comparison, track dominance and the rest |
| `schema/published-v2.schema.json` | The published format, written from the models in `f1data/models.py`. The site's types are generated from it |
| `worker/src/data.mjs` | The read-only Worker, deployed as `formula-1-data-read` (`wrangler.data.jsonc`) |
| `frontend/` | The site. `src/lib/published/` reads the published layout |
| `tests/` | The data plane's tests, and a sample dataset for working on the site offline |
| `docs/` | The guide to the data plane, the architecture review, and two documents about the old path |
| `.github/workflows/` | Tests, the build and publish job, the Worker's deployment, and the old path's workflows |

Still in the tree, and not used by the site on this branch: `pipeline/`, the
rest of `backend/`, the Worker in `worker/src/index.mjs` with `migrations/` and
`wrangler.jsonc`, and the workflows that ingest through them. That is the path
this one replaces, described in
[`docs/old-data-path.md`](docs/old-data-path.md). It is removed once the new
path has carried three race weekends unattended.

## Working on the site

Node 22 or later (the site is built with 22 in CI, and tested with 24):

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. The site reads the deployed Worker, which is
public and read-only, so nothing else needs to be running. To work without the
network, or against data that does not change, serve the sample dataset and
point the site at it. In a second terminal, at the root of the repository and
with the Python environment described below:

```powershell
python -m tests.sample_bucket .sample --serve
```

```text
# frontend/.env.local
NEXT_PUBLIC_PUBLISHED_DATA_BASE_URL=http://localhost:8788/data
```

The sample race is then at `/session?key=9001`.

`npm run lint` and `npm run build` are what CI runs; the static export is
written to `frontend/out`. `npm run types` regenerates the site's types from
the schema, and a test fails when the committed types are not what the schema
makes.

## Working on the data plane

Python 3.12, with the pinned packages:

```powershell
py -3.12 -m venv C:\venvs\f1data
C:\venvs\f1data\Scripts\python.exe -m pip install -r requirements-dev.txt
C:\venvs\f1data\Scripts\Activate.ps1
```

With the environment activated, `python` below is that one; without, write
its full path in place of the word. From the root of the repository:

```powershell
python -m f1data fetch-due --dry-run     # what would be fetched; changes nothing in the store or the spool
python -m f1data run                     # the whole job: build, fetch what is due, build what was fetched
python -m f1data build                   # build and publish what the archive holds
```

Each needs a store: `--store <directory>` for one on disk, made first, or
`--store r2` with the credentials in `.env` (`.env.example` lists them). The
versions are pinned because a snapshot in the archive is FastF1's cache as
that version of FastF1 wrote it.

## Tests

```powershell
python -m pytest tests -q                      # the data plane
python -m pytest backend/tests -q              # the analyses and the old pipeline (backend/requirements-dev.txt)
node --test "worker/tests/*.test.mjs"          # both Workers
cd frontend; npm test                          # the site's reader and view logic
```

`tests.yml` runs all four on every pull request. Some of the data plane's
tests run against real archived sessions and are skipped without them; the
guide says how to point them at an archive ("Testing against recorded races").

## Deployment

| What | Where | How |
| --- | --- | --- |
| The site | Cloudflare Pages, from `frontend/` (`npm ci && npm run build`, output `out`) | Pages builds each branch; `cloudflare-pages.yml` deploys by hand |
| The read-only Worker | `formula-1-data-read` | `deploy-data-worker.yml`, by hand, and on a push to `main` that touches the Worker |
| Published data | The R2 bucket `formula-1-data-artifacts`, under `v2/` | `publish.yml` builds from the archive; whatever fetches, by hand now and the scheduled task once it is registered, fetches into it |

Nothing in the site's build needs a secret. The address of the Worker is in
the committed `frontend/.env.production`.

## Limits worth knowing

- Races and sprints only. The job fetches no practice or qualifying. `fetch`
  by hand archives any session, and nothing is built or shown of one that
  is not a race or a sprint.
- The fetch needs a network that F1's archive answers. Without the scheduled
  task running on such a machine, nothing new arrives.
- The stop list is every entry to the pit lane in the timing, with F1's own
  figures for it where F1 sent them. Not every entry is a pit stop: a car
  that serves a drive-through penalty, or follows the safety car down the pit
  lane, is listed and marked as having gone through, when F1's pit-stop feed
  reports no stop and its tyre data has the car on the same tyres afterwards.
  The pit-stop feed leaves out about one stop in eleven, and the pit-lane
  figures are of the stops it reports.
- Tyre degradation, pit loss, undercuts and the pace prediction are estimates
  from a model, not measurements.
