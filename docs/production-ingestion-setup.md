# Production ingestion setup

This runbook completes the account-level setup for the Cloudflare Worker, R2, D1, Queues,
GitHub Actions runner, scheduled ingestion, and optional Cloudflare Access protection.

Run commands from the repository root. On Windows, use `npx.cmd`; on macOS or Linux, replace it
with `npx`.

## 1. Commit and push the repository changes

The Worker can be deployed from local files, but GitHub cannot run the new workflows until they are
on the repository's default branch.

Review the current changes, then commit and push them using your normal Git workflow.

## 2. Authenticate Wrangler

```powershell
npx.cmd --yes wrangler@latest login
npx.cmd --yes wrangler@latest whoami
```

Use Wrangler 4.x. Wrangler's current command reference is available in the
[Cloudflare documentation](https://developers.cloudflare.com/workers/wrangler/commands/).

## 3. Verify the Cloudflare resources

The checked-in configuration expects these resources:

| Resource | Name |
|---|---|
| Worker | `formula-1-data-api` |
| R2 bucket | `formula-1-data-artifacts` |
| Preview R2 bucket | `formula-1-data-artifacts-dev` |
| D1 database | `formula-1-data` |
| Queue | `f1-ingestion-jobs` |
| Dead-letter queue | `f1-ingestion-jobs-dlq` |

Check what exists:

```powershell
npx.cmd --yes wrangler@latest r2 bucket info formula-1-data-artifacts
npx.cmd --yes wrangler@latest d1 info formula-1-data
npx.cmd --yes wrangler@latest queues list
```

Create only missing primary resources:

```powershell
npx.cmd --yes wrangler@latest r2 bucket create formula-1-data-artifacts
npx.cmd --yes wrangler@latest r2 bucket create formula-1-data-artifacts-dev
npx.cmd --yes wrangler@latest d1 create formula-1-data
npx.cmd --yes wrangler@latest queues create f1-ingestion-jobs
```

If you create a new D1 database, replace `database_id` in `wrangler.jsonc` with the ID printed by
Wrangler. The Worker deployment creates or attaches the configured dead-letter queue.

Keep direct public access to the R2 bucket disabled. Public artifacts should be served by the Worker,
which blocks the private `source/` prefix.

## 4. Apply D1 migrations

Preview pending migrations, then apply them:

```powershell
npx.cmd --yes wrangler@latest d1 migrations list formula-1-data --remote
npx.cmd --yes wrangler@latest d1 migrations apply formula-1-data --remote
```

Verify the tables and active-job index:

```powershell
npx.cmd --yes wrangler@latest d1 execute formula-1-data --remote --command "select name from sqlite_schema where type in ('table','index') order by name"
```

## 5. Seed the required R2 indexes

Queue-driven ingestion deliberately refuses to publish unless the current R2 `catalog.json` can be
downloaded first. The download is retried with backoff, and a persistent failure aborts the run. This
prevents a temporary credential or R2 failure from replacing the production catalog with a partial
local build: Wrangler reports "no such object" and "that read failed" the same way, so a runner that
tolerated an unreadable catalog would republish an index holding only the session it just ingested.

This step is what makes that requirement satisfiable, so do not skip it.

Upload the catalog and all checked-in season indexes:

```powershell
npx.cmd --yes wrangler@latest r2 object put formula-1-data-artifacts/catalog.json --file frontend/public/data/catalog.json --remote

Get-ChildItem frontend/public/data/seasons -Filter *.json | ForEach-Object {
    $key = "seasons/$($_.Name)"
    npx.cmd --yes wrangler@latest r2 object put "formula-1-data-artifacts/$key" --file $_.FullName --remote
}
```

Verify the catalog without modifying the repository:

```powershell
$check = Join-Path $env:TEMP "formula1data-catalog-check.json"
npx.cmd --yes wrangler@latest r2 object get formula-1-data-artifacts/catalog.json --file $check --remote
(Get-Content -Raw $check | ConvertFrom-Json).totals
```

Existing session files may continue to come from the configured Pages fallback. New and refreshed
sessions will be written to R2. If you want R2 to contain every historical artifact immediately,
upload the remaining files under `frontend/public/data` while preserving their relative paths.

### Bootstrapping without a seed

If you would rather have the first ingestion create the indexes in a genuinely empty bucket, run that
one job manually from a machine with Wrangler credentials and add `--allow-missing-catalog`:

```powershell
python -m pipeline process-queue --message-file .\message.json --artifact-destination r2 --r2-bucket formula-1-data-artifacts --allow-missing-catalog
```

The flag makes an unreadable catalog mean "empty bucket" instead of an error, which is only true
once. Never set it for the `Process ingestion job` workflow or any routine run: on a populated bucket
it turns a transient read failure into a silent overwrite of the published index with a
single-session catalog. Verify the catalog with the `r2 object get` check above before the next run,
and after that the normal fail-loud path applies.

## 6. Create the GitHub dispatch token

The Worker uses `repository_dispatch` to start the Python ingestion workflow.

1. In GitHub, create a fine-grained personal access token.
2. Limit repository access to `Ntrxi/Formula1Data`.
3. Grant repository **Contents: Read and write**.
4. Store the token in a password manager.

GitHub currently requires Contents write permission for the repository-dispatch endpoint; see the
[GitHub repository dispatch documentation](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event).

Add it to the Worker interactively:

```powershell
npx.cmd --yes wrangler@latest secret put GITHUB_DISPATCH_TOKEN
```

Paste the token at Wrangler's prompt. Do not place it in `.dev.vars`, `wrangler.jsonc`, a command
argument, or a committed file.

## 7. Create the ingestion callback token

Generate one high-entropy token in a password manager. The exact same value must be stored in two
places:

1. As the Worker secret `INGESTION_API_TOKEN`:

   ```powershell
   npx.cmd --yes wrangler@latest secret put INGESTION_API_TOKEN
   ```

2. As the GitHub Actions repository secret `INGESTION_API_TOKEN`:

   `GitHub repository → Settings → Secrets and variables → Actions → New repository secret`

The token authenticates job-status callbacks and can also authenticate non-browser ingestion
requests when `REQUIRE_INGESTION_REQUEST_AUTH=true`.

## 8. Create the Cloudflare token used by GitHub Actions

The Python workflow calls Wrangler to read and write objects in R2. Create a scoped Cloudflare API
token with bucket-item read/write access to `formula-1-data-artifacts`. If bucket-level permission is
not available in the token UI, use account-level **Workers R2 Storage Write**, restricted to the
correct Cloudflare account. See [R2 token permissions](https://developers.cloudflare.com/r2/api/tokens/).

Add these GitHub Actions repository secrets:

| Secret | Value |
|---|---|
| `CLOUDFLARE_API_TOKEN` | The scoped Cloudflare API token |
| `CLOUDFLARE_ACCOUNT_ID` | The Cloudflare account ID |

Cloudflare documents these two CI values in its
[GitHub Actions guide](https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/).

Add these GitHub Actions repository variables:

| Variable | Value |
|---|---|
| `WORKER_BASE_URL` | The final Worker origin, without a trailing slash |
| `R2_BUCKET` | `formula-1-data-artifacts` |

Example Worker origin: `https://api.example.com` or the assigned `workers.dev` origin.

## 9. Choose an ingestion security model

### Recommended: Cloudflare Access

Use this when you want the site's browser ingestion panel to remain available to you.

1. Put the Worker on a hostname in your Cloudflare zone, such as `api.example.com`.
2. Create a self-hosted Access application for `api.example.com/api/ingestion/*`.
3. Add an Allow policy restricted to your identity.
4. Create an Access service token named `formula1data-github-actions`.
5. Add a **Service Auth** policy to the application for that service token.
6. Disable the unprotected `workers.dev` route after the custom hostname works.
7. Leave `REQUIRE_INGESTION_REQUEST_AUTH=false` in `wrangler.jsonc`; Access is the browser-facing
   authorization layer, while callbacks still require `INGESTION_API_TOKEN`.

Add the service token values as GitHub Actions repository secrets:

| Secret | Value |
|---|---|
| `CF_ACCESS_CLIENT_ID` | Access service-token client ID |
| `CF_ACCESS_CLIENT_SECRET` | Access service-token client secret |

Cloudflare only shows the client secret once. The GitHub scheduler and ingestion callback send both
service-token headers. Cloudflare's current setup steps are in the
[Access service-token guide](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/).

### Simpler alternative: bearer-token-only ingestion

If you do not need browser-triggered ingestion, set this in `wrangler.jsonc`:

```jsonc
"REQUIRE_INGESTION_REQUEST_AUTH": "true"
```

The GitHub scheduler will continue to work with `INGESTION_API_TOKEN`, but the browser ingestion
panel cannot safely carry that secret and will receive `401` responses. Historical reads and session
status checks remain public.

## 10. Confirm the public origins

Set `CORS_ALLOW_ORIGIN` in `wrangler.jsonc` to the exact Pages or custom frontend origin. It is
currently:

```text
https://formula1data.pages.dev
```

Set `STATIC_DATA_BASE_URL` to the Pages `/data` origin used as the fallback for artifacts not yet in
R2. Do not use `*` for CORS in production.

## 11. Deploy the Worker

Validate without deploying:

```powershell
npx.cmd --yes wrangler@latest deploy --dry-run
```

Deploy:

```powershell
npx.cmd --yes wrangler@latest deploy
```

This activates the Queue consumer, dead-letter queue, 30-minute stale-job reconciliation cron, D1
and R2 bindings, narrowed CORS setting, and public artifact allowlist.

Check the health endpoint:

```powershell
Invoke-RestMethod "$env:WORKER_BASE_URL/health"
Invoke-RestMethod "$env:WORKER_BASE_URL/data/catalog.json" | Select-Object generated_at, totals
```

If `WORKER_BASE_URL` is not set in your shell, replace it with the actual Worker origin.

## 12. Validate GitHub Actions

In `GitHub → Actions`:

1. Run **Backfill F1 data** with `dry_run=true`, a single year, and `races_only=true`.
2. Confirm the log lists candidates without creating jobs.
3. Run **Schedule completed session ingestion** manually with `force=false`.
4. Confirm it either queues recent completed sessions or reports that they are already active/ready.

Scheduled workflows run only from the default branch. If the workflow does not appear, confirm the
changes were pushed and GitHub Actions are enabled for the repository.

## 13. Perform one real-session smoke test

Choose one completed session that is not already in R2, then request it from the site's ingestion
panel or run the scheduler/backfill workflow for its year and session code.

Watch the job in D1:

```powershell
npx.cmd --yes wrangler@latest d1 execute formula-1-data --remote --command "select job_id, session_id, status, attempts, error_message, created_at, finished_at from ingestion_jobs order by created_at desc limit 10"
```

Expected progression:

```text
queued → running → succeeded
```

Then verify the session manifest and normalized source dataset:

```powershell
npx.cmd --yes wrangler@latest r2 object get formula-1-data-artifacts/sessions/SESSION_ID/manifest.json --file "$env:TEMP/session-manifest.json" --remote
npx.cmd --yes wrangler@latest r2 object get formula-1-data-artifacts/source/sessions/SESSION_ID/dataset.json --file "$env:TEMP/session-source.json" --remote
```

Replace `SESSION_ID` with a value such as `2026-09-r`. Finally, open the session in the frontend and
check summary, laps, analysis, and telemetry.

## Troubleshooting

| Symptom | Check |
|---|---|
| Job immediately fails with no runner configured | Confirm Worker secret `GITHUB_DISPATCH_TOKEN` and the configured GitHub owner/repository. |
| GitHub dispatch returns 401/404 | Confirm the fine-grained token is scoped to this repository with Contents write permission. |
| Runner cannot hydrate `catalog.json` | Confirm the R2 seed exists and GitHub's Cloudflare token has object read/write access. The read is already retried with backoff, so a reported failure is a missing seed or a credential problem, not a blip. Only a genuinely empty bucket warrants `--allow-missing-catalog`. |
| Callback receives 401 | Confirm `INGESTION_API_TOKEN` matches in Worker and GitHub; if Access is enabled, also confirm both Access secrets and the Service Auth policy. |
| Browser ingestion receives 401 | Either sign in through Access or verify whether bearer-only mode intentionally disables browser ingestion. |
| Session succeeds but is absent from navigation | Inspect R2 `catalog.json` and `seasons/{year}.json`; the runner publishes these after the session manifest. |
| Job remains running | Wait for the two-hour stale-job threshold or inspect the GitHub workflow; the Worker cron will mark stale jobs failed. |
| Queue retries are exhausted | Inspect `f1-ingestion-jobs-dlq` and the Worker logs before retrying. |

Tail Worker errors during a smoke test:

```powershell
npx.cmd --yes wrangler@latest tail formula-1-data-api --status error
```

## Rollback

List Worker versions and roll back the deployment if necessary:

```powershell
npx.cmd --yes wrangler@latest versions list
npx.cmd --yes wrangler@latest rollback
```

To stop automatic ingestion without rolling back code, disable **Schedule completed session
ingestion** in GitHub Actions. Existing historical artifacts in R2 and Pages remain readable.

Do not delete R2 objects or D1 records during rollback. Preserve them until the previous Worker
version is confirmed healthy.
