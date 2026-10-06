# The data plane

How a session gets from F1's timing archive to a page. The design and the
reasons for it are in `docs/architecture-review-findings.md`, section 6; this
is how to run it.

```text
F1 archive --> fetch -----------> source archive --> build ----------> R2
               (a machine F1      in R2              (any machine;     generation per publish,
                answers)          one snapshot       never asks F1)    pointer written last
                                  per fetch                                 |
Jolpica ----------------------------------------------^                    |
                                                                            |
browser <--- static site, pages load at runtime <--- read-only Worker ------+
```

Two stages, kept apart. **Fetch** copies a session from F1 into the archive and
is the only stage that needs a network F1 answers; F1 refuses GitHub-hosted
runners with 403. **Build** reads the archive, Jolpica and FastF1's schedule
file, and can run anywhere.

## What is in the bucket

```text
archive/sessions/<session_key>/<snapshot_id>/     never served
    fastf1-cache.tar.gz        FastF1's parsed feeds
    http-cache.sqlite.gz       the raw HTTP responses
    extra/PitStopSeries.jsonStream, extra/circuit-info.json
    snapshot.json              written last; without it the snapshot does not exist
    remeasured.json            only where a build found the snapshot's record wrong
archive/legacy/<name>-<id>.tar.gz + .json         a whole directory, kept as it was

v1/pointers/<session_key>.json                    one per published session
v1/generations/<session_key>/<generation>/        immutable; manifest.json written last
v1/index.json                                     the calendar, with published sessions attached
v1/standings/<year>.json
```

A session is named by F1's session key, not by its round: rounds move when the
calendar changes. `v1` is the artifact format; a new format is published under
a new prefix before the site that reads it is deployed.

## Commands

All of them are `python -m f1data <command>`, from the repository root, with
`pip install -r requirements.txt`. `--store` is a directory or `r2`, and
defaults to the `F1DATA_STORE` environment variable.

| Command | What it does |
| --- | --- |
| `run` | The whole job: `fetch-due`, then `build`. What a schedule runs |
| `fetch-due` | Fetch every finished race and sprint the archive does not hold in full. `--dry-run` to see the plan |
| `fetch --year Y --event E --session S` | Fetch one session as a new snapshot |
| `build` | Build and publish every archived session that needs it, then the index and standings. `--session-key K` to limit; `--shard I/N` to split across jobs |
| `probe --year Y --event E --session S` | Fetch one session into a scratch directory and report what F1 answered. Archives nothing |
| `copy-archive --from A --to B` | Copy snapshots between stores, such as a local directory to `r2`. A correction of a snapshot's record is not copied: the destination's builds measure for themselves |
| `archive-directory --path P --name N` | Keep a whole directory in the archive as one file, such as an old FastF1 cache |

Every command is safe to repeat. A snapshot and a generation are written once
under a name of their own. A pointer, the index and the standings are written
against the version that was read, so two runs at once cannot lose each other's
work: the one that loses a write reads again and decides again. That holds for
a directory as it does for `r2`: two runs sharing a directory take a lock on
it for each write.

One session failing to fetch does not stop the others. After two failures in
a row `fetch-due` asks F1's archive for the season's index: if that answers,
the fault is with those sessions and the batch carries on; if it does not,
nothing can be fetched and the batch stops until the next run.

## Credentials

R2 is reached through its S3 API. Put these in `.env` at the repository root
(it is ignored by git), or in the environment:

```text
F1DATA_STORE=r2
R2_BUCKET=formula-1-data-artifacts
R2_ACCOUNT_ID=<Cloudflare account id>
R2_ACCESS_KEY_ID=<from an R2 API token with Object Read & Write on the bucket>
R2_SECRET_ACCESS_KEY=<from the same token>
```

`CLOUDFLARE_API_TOKEN` works in place of the key pair, which is how the
workflows publish with the secret the repository already has.

## Running on a schedule

Fetching has to run on a machine F1 answers, which rules out hosted runners
(decision 2 of the plan: a scheduled task on a local machine). With the
credentials above in `.env`, `python -m f1data run` is the whole job, and it is
safe to run as often as you like: it fetches only what is due and builds only
what changed. Every three hours is plenty for the 48-hour bar.

On Windows, from PowerShell, with the two paths set to yours:

```powershell
$repo   = "C:\path\to\Formula1Data"
$python = "C:\path\to\venv\Scripts\python.exe"
$log    = "$env:LOCALAPPDATA\f1data\run.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

$action   = New-ScheduledTaskAction -Execute "cmd.exe" -WorkingDirectory $repo `
              -Argument "/c `"`"$python`" -m f1data run >> `"$log`" 2>&1`""
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
              -RepetitionInterval (New-TimeSpan -Hours 3)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
              -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "Formula1Data run" -Action $action -Trigger $trigger -Settings $settings
```

`-StartWhenAvailable` runs a missed start when the machine comes back on, and
the job catches up on anything it missed, because F1's archive keeps past
sessions. The machine does not have to be on when a session finishes. Nothing
has registered this task yet.

## When a session counts as complete

`fetch` measures what arrived, per driver and per feed, and stores the figures
with the snapshot (`f1data/coverage.py`). A race or sprint is complete when:

- every feed arrived, the session status shows it ended, and Jolpica has its
  classification;
- every classified driver has at least the laps they are classified with;
- for each driver, 95% of those laps have car data, position data, and a tyre
  compound and stint. A lap counts for car or position data only if its samples
  run from the start of the lap to its end with no hole longer than 5 seconds;
- a race whose timing shows pit stops has F1's pit-stop feed, and the circuit's
  corner positions arrived.

A session short of a bar is fetched again every 6 hours for 48 hours after its
first fetch, each time from an empty cache as a new snapshot. Build picks the
best snapshot by a fixed order. If the session is still short when the 48 hours
are up it is published as partial, and its pointer names what is short. After
that it is fetched weekly, unless what is missing is a feed F1 answered that it
does not hold: one that is absent outright, from a fetch F1 was otherwise
answering. A feed that arrived and is short is always fetched again. The limits
are in `f1data/policy.py`.

A snapshot is judged against the classification of the day, which is the whole
answer: a driver it leaves out has no result and no laps to account for. A
session published short stays on the fetch stage's list however old it is,
because a result corrected months later can be what left it short.

The figures a snapshot is judged by were recorded when it was fetched. A build
measures the feeds again once it has loaded them, and if they are not what the
record says it writes the figures it measured beside the snapshot, as
`remeasured.json`, publishes nothing from that judgement and decides again.
Every reader of the archive is given a corrected snapshot with the corrected
figures, so the fetch stage, the choice of snapshot and the build always judge
the same thing.

A correction is written against the one that was read, so a build never
replaces one it has not seen, and one written by a newer pipeline version is
left alone, as a newer version's pointer is. A pointer records which figures
its session was judged by; if they are corrected afterwards the session is
decided again, and the build that follows measures the feeds once more, so a
wrong correction does not outlive the next run.

## When a session is built again

The pointer records what its generation was built from: the snapshot and a
checksum of its record (`record`), the fingerprint of what Jolpica supplied
(the classification and, for a race, each driver's first-lap time), the
calendar entry (year, round, names and a checksum of the whole calendar row,
under `also`), and the pipeline version. `build` builds a session again when
any of them differs from what it would use now. Jolpica's two answers are used
together only when both say they are of the same race.

Those are looked up once, after the pointer is read, on every attempt, and the
calendar again before the index is written: a publisher never decides from
something it looked up before the version its write is guarded by. The
artifacts are then made with every network request refused. FastF1 would
otherwise fetch the result and the first-lap times itself while loading, and
look the round up in the calendar a second time; a build is made of what was
gathered and of the archive, and of nothing else.

A session more than 30 days old is looked up in the calendar on every run, but
Jolpica is asked for its classification on two days in every thirty, after a
lost write, and whenever `build --recheck` is given.

## Workflows

| Workflow | Runs | Purpose |
| --- | --- | --- |
| `publish.yml` | Manually, or on a push that touches it | `build` against R2, in four parallel parts |
| `deploy-data-worker.yml` | On a push that touches the Worker | Tests and deploys `formula-1-data-read` |
| `r2-contract.yml` | On a push that touches the store | The store's tests against the real bucket |
| `probe-f1-access.yml` | Manually | Whether F1 answers a hosted runner yet |
| `upload-archive-spool.yml` | Manually | Stopgap: copies a fetch made without R2 credentials into the bucket. Delete it once the fetch machine has credentials |

## Checking a publication

After a `build`, with `B=https://formula-1-data-read.aaronchenxi2.workers.dev/data`:

1. `curl -s $B/v1/index.json` lists the calendar, and the session has a
   `session_key` and `complete`.
2. `curl -si $B/v1/pointers/<key>.json` is a 200 with
   `cache-control: public, max-age=30, ...`. Its `generation` is 64 hex
   characters and equals `manifest.sha256`.
3. `curl -si $B/v1/generations/<key>/<generation>/manifest.json` is a 200, not a
   206, with `cache-control: ... immutable`.
4. `curl -si $B/archive/sessions/<key>/` and any `archive/` path is a 404. The
   archive is never served.
5. After a second publication of the same session, the first generation's paths
   still answer 200. Nothing is pruned.
6. The page `/session?key=<key>` shows the session, and so does
   `/session?year=<year>&round=<round>&session=<type>`. Opening a tab requests
   only that tab's artifacts: the position replay and the telemetry laps are
   not requested until their tabs are opened.

## What is not here yet

The artifact contents are still in the old format, reached through
`f1data/legacy.py`. Every page now loads its data in the browser and the site
builds without `frontend/public/data`, but that directory is still in git, and
the old build-time dashboard code it fed is still in the tree, unreachable.
Nothing runs `run` on a schedule yet. See section 10 of the findings document
for the state of each step.

## The pages

Every page reads the published data at runtime, from the base URL in
`NEXT_PUBLIC_PUBLISHED_DATA_BASE_URL`.

| Page | Address | Reads |
| --- | --- | --- |
| Home | `/` | The index, then the latest published session's summary files |
| Seasons, season, meeting, circuits | `/seasons`, `/season?year=`, `/meeting?year=&round=`, `/circuits` | The index only |
| Session | `/session?key=<session key>` | The index and the pointer, then each tab's files when the tab is opened |
| Strategy, telemetry, drivers, teams | `/strategy?key=`, and so on | One session's files; the latest published session when no key is given |
| Standings | `/standings?year=` | The index and `v1/standings/<year>.json` |

A session is linked by its key. `/session?year=&round=&session=` still opens
one, and the page then offers the link by key, since a round moves when the
calendar changes.
