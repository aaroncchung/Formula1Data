# Validating the generation layout against a real bucket

Everything in the R2 publication path is tested against a mocked `subprocess.run`. This runbook is
the one live check that design needs, and it is worth running once before the generation change
reaches production. There is no rollback path any more — the pointer flip is the only commit — so
what has to be confirmed is that the flip behaves, not that a recovery works.

Use a **throwaway bucket**. Every step here writes, and step 5 deliberately fails a publication.

```powershell
$env:R2_BUCKET = "formula-1-data-generations-test"
npx.cmd --yes wrangler@latest r2 bucket create $env:R2_BUCKET
$SESSION = "2025-01-r"     # any session with committed artifacts under frontend/public/data
```

A helper, since every step inspects the same three things:

```powershell
function Show-Generation {
  param($Session)
  $tmp = Join-Path $env:TEMP "active.json"
  npx.cmd --yes wrangler@latest r2 object get "$env:R2_BUCKET/sessions/$Session/active.json" --file $tmp --remote 2>$null
  if (-not (Test-Path $tmp)) { Write-Host "no pointer"; return }
  $pointer = Get-Content -Raw $tmp | ConvertFrom-Json
  Write-Host "live:     $($pointer.artifact_base_path)"
  Write-Host "previous: $($pointer.previous_generation)"
  Remove-Item $tmp
}
```

## 1. First publication into an empty bucket

```powershell
python -m pipeline process-queue --message-file .\message.json `
  --artifact-destination r2 --r2-bucket $env:R2_BUCKET --allow-missing-catalog
Show-Generation $SESSION
```

Expect a pointer with `previous: ` empty. Then confirm **nothing was written at the conventional
key** — this is what makes the flip, rather than any individual upload, the moment a session changes:

```powershell
npx.cmd --yes wrangler@latest r2 object get "$env:R2_BUCKET/sessions/$SESSION/manifest.json" --file nul --remote
```

This must fail with a not-found error. If it succeeds, the publisher is still writing the old layout.

## 2. Reads resolve through the pointer

Point a Worker at the test bucket and fetch a conventional path:

```powershell
curl.exe -s -o nul -w "%{http_code}`n" "$env:WORKER_BASE_URL/data/sessions/$SESSION/summary.json"
```

Expect `200`. The frontend builds this URL from hardcoded filenames and never sees a generation, so
this is the check that the Worker resolver and the publisher agree in production and not just in
`worker/tests/generation-contract.test.mjs`.

## 3. Two consecutive no-force runs — the regression that shipped once

This is the most important step. Generation ids are content-addressed, so republishing unchanged
artifacts lands on the same id. A bug in the first version of this change made the third such
publication delete the live generation, leaving `active.json` pointing at nothing.

Run the **same command as step 1** twice more, without `--force`:

```powershell
python -m pipeline process-queue --message-file .\message.json --artifact-destination r2 --r2-bucket $env:R2_BUCKET
Show-Generation $SESSION
python -m pipeline process-queue --message-file .\message.json --artifact-destination r2 --r2-bucket $env:R2_BUCKET
Show-Generation $SESSION
```

Expect `live` unchanged across all three runs and `previous` **never equal to `live`**. Then confirm
the session is still readable — this is the assertion that matters, because the pointer surviving
tells you nothing about whether its objects did:

```powershell
curl.exe -s -o nul -w "%{http_code}`n" "$env:WORKER_BASE_URL/data/sessions/$SESSION/summary.json"
```

Still `200`. A `404` here means the live generation was pruned: stop and do not deploy.

## 4. A forced refresh flips and prunes

```powershell
python -m pipeline process-queue --message-file .\message.json --artifact-destination r2 --r2-bucket $env:R2_BUCKET --force
Show-Generation $SESSION
```

Expect a **new** `live`, and `previous` naming the generation from step 3. Reads keep returning
`200` throughout — the flip is a single PUT, so there is no window where a client sees a mixture.

Run it once more and the generation from step 3 should be pruned, while step 4's is retained. Confirm
the retained one survives, since a reader that resolved the pointer just before a flip is still
fetching from it:

```powershell
npx.cmd --yes wrangler@latest r2 object get "$env:R2_BUCKET/<previous_from_Show-Generation>/manifest.json" --file nul --remote
```

## 5. An injected mid-upload failure must not move the pointer

The failure mode F-02 was filed for. `--force` so it republishes, and fail the fifth upload:

```powershell
python - <<'PY'
import pipeline.local_queue_worker as w

calls = {"n": 0}
real = w.upload_r2_object

def flaky(path, bucket, key):
    calls["n"] += 1
    if calls["n"] == 5:
        raise RuntimeError("injected upload failure")
    return real(path, bucket, key)

w.upload_r2_object = flaky
w.process_message(
    {"job_id": "validate", "kind": "refresh_session", "year": 2025, "round": 1, "session": "R"},
    artifact_destination="r2",
    r2_bucket="formula-1-data-generations-test",
    force=True,
)
PY
```

The run must fail. Then:

```powershell
Show-Generation $SESSION
curl.exe -s -o nul -w "%{http_code}`n" "$env:WORKER_BASE_URL/data/sessions/$SESSION/summary.json"
```

`live` must be **unchanged from step 4** and the read must still return `200`. The half-written
generation is inert — nothing points at it — and it is not reclaimed. That leak is documented and
accepted; see F-02's residual in `docs/code-review-findings.md`.

## 6. A legacy session with no pointer still serves

Sessions published before this change have no `active.json`, and the resolver must treat an absent
pointer differently from an unreadable one:

```powershell
npx.cmd --yes wrangler@latest r2 object put "$env:R2_BUCKET/sessions/2024-01-r/manifest.json" `
  --file frontend/public/data/sessions/2024-01-r/manifest.json --remote
npx.cmd --yes wrangler@latest r2 object put "$env:R2_BUCKET/sessions/2024-01-r/summary.json" `
  --file frontend/public/data/sessions/2024-01-r/summary.json --remote
curl.exe -s -o nul -w "%{http_code}`n" "$env:WORKER_BASE_URL/data/sessions/2024-01-r/summary.json"
```

Expect `200`, served from the conventional key.

## 7. Tear down

```powershell
npx.cmd --yes wrangler@latest r2 bucket delete $env:R2_BUCKET
```

## What a pass means

Steps 1–6 green means the flip is atomic, pruning cannot reach a live generation, a failed
publication leaves the previous one serving, and both layouts coexist. What it does **not** cover:
concurrent publications of the same session (nothing serialises them — the queue is expected to),
and reclaiming orphaned generations, which needs an object listing wrangler does not expose.
