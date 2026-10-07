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
    extra/PitStopSeries.jsonStream, extra/WeatherData.jsonStream, extra/circuit-info.json
    snapshot.json              written last; without it the snapshot does not exist
    remeasured.json            only where a build found the snapshot's record wrong
archive/legacy/<name>-<id>.tar.gz + .json         a whole directory, kept as it was
archive/attempts/<year>/<start>-<type>.json       a note that a fetch of that session failed

v2/pointers/<session_key>.json                    one per published session
v2/generations/<session_key>/<generation>/        immutable; manifest.json written last
v2/index.json                                     the calendar, with published sessions attached
v2/standings/<year>.json
```

A snapshot's marker has to describe the snapshot it is filed as: the session
key and the snapshot id in its key, with a measurement in which every figure
is a figure, a fetch time and a start time that can be read, and its parts
listed. One
that does not, or that cannot be read, is passed over with an error in the
log, like an upload that never finished, and the rest of the archive is read
as usual.

A session is named by F1's session key, not by its round: rounds move when the
calendar changes. `v2` is the artifact format; a new format is published under
a new prefix before the site that reads it is deployed. What was published
under `v1/` stays where it is until nothing reads it.

## The published format

Every object under `v2/` has a model in `f1data/models.py`, and that file is
the contract: an artifact is built as its model and written from it, so a field
that is not declared cannot be published and a value of the wrong kind stops
the build. `python -m f1data schema` writes the models out as
`schema/published-v2.schema.json`, which is what the frontend's types are
generated from. A test fails when the committed file and the models disagree.

A generation of a race is about 45 objects and 20 MB:

```text
summary.json  drivers.json  laps.json  results.json  stints.json  pit-stops.json
weather.json  race-control.json  corners.json  coverage.json  position-replay.json
analysis/<name>.json              nine analyses; a tenth for practice sessions
telemetry/index.json              which laps have telemetry, with each lap's time
telemetry/<driver_code>.json      every lap of one driver, as parallel arrays
manifest.json                     every file with its size and SHA-256
```

What holds for all of them:

- A missing value is `null`. Times are whole milliseconds; a position in time
  counts from the moment the session clock read zero, which `summary.json`
  gives in UTC.
- Every other number that is not whole is rounded as it is written, to the
  precision its field states. With keys sorted and one newline at the end,
  that makes two builds of one snapshot and one classification the same bytes
  on any machine, and so the same generation.
- No artifact takes anything from the calendar. A session is described in
  F1's own words, and its round is looked up in the index. The manifest and
  the pointer carry the session's identity, and two things in that are the
  calendar's: the start time, and the round as it was when the session was
  fetched.
- Telemetry is published at up to 300 samples a lap. The analyses read every
  sample.
- A lap has telemetry when its car data runs from its start to its end with no
  hole longer than 5 seconds, which is the test the coverage counts laps by:
  what is published is what is counted. FastF1 gives a car that is missing
  from part of the car feed rows of zeros for the moments it missed; those are
  not samples and are left out (`sent_by_f1` in `f1data/coverage.py`). A lap
  that has positions and no telemetry is still in the replay, with no speed.
- A driver's stints are consecutive runs of laps that never overlap. A lap
  with no compound stays with the set it is numbered with.
- A pit stop is the timing's entry to the pit lane with F1's own figures
  beside it, matched by driver and lap. F1's feed sends a stop once and then
  only what changes, so a stop is followed by its driver and its place in
  that driver's list, and a correction lands on the stop it corrects. F1
  sometimes reports a stop late and with no lap; such a report goes to the
  stop the timing shows the car finishing in the two minutes before it, when
  there is exactly one that no other report names and whose pit-lane time is
  the report's own, and is left out otherwise. A car in the pit lane while the
  session was red-flagged is marked `under_red_flag`, and the strategy
  analysis leaves its wait out of the pit-lane figures.
- A driver is found by car number in every feed and named by F1's three
  letters, from the timing, the driver list or the classification. A driver
  none of them names is published under the car number as text. FastF1
  writes the word `None` where a code is missing; no reader takes that, or
  any other text, on trust (`f1data/loaded.py`).
- A weather reading is null where F1 sent none. FastF1 writes 0 for those, so
  the feed itself is archived with the session and asked. Snapshots taken
  before it was kept are published as FastF1 has them; every line of every
  one of those 51 sessions gives every reading.
- The lap a replay frame says the session had reached is the timing's: the
  highest lap any car had started by the end of the frame's window, whether
  or not either feed has samples for it.

## Testing against recorded races

`tests/test_recorded_race.py` builds real sessions from the source archive: it
compares the telemetry with FastF1's own, checks a golden build of the 2026
Austrian GP file by file, removes each feed in turn to show that a coverage
bar notices, and checks three things F1's feeds have done that a stand-in
would not think of (rows FastF1 adds for cars missing from the car feed, pit
stops reported with no lap, a car whose data stops before its lap does). It
also builds the Austrian race with each of its feeds taken out in turn, since
a session can measure correctly and still fail to build. It needs no network,
and runs when it is told where the archive is:

```text
F1DATA_TEST_ARCHIVE=<a directory store, or r2> python -m pytest tests/test_recorded_race.py -s
```

After an intended change to what a build produces, record the golden file
again by adding `F1DATA_WRITE_FIXTURES=1`.

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
| `schema` | Write the published format's JSON Schema from the models. `--check` to fail when the committed file is out of date |

Every command is safe to repeat. A snapshot and a generation are written once
under a name of their own. A pointer, the index and the standings are written
against the version that was read, so two runs at once cannot lose each other's
work: the one that loses a write reads again and decides again. That holds for
a directory as it does for `r2`: two runs sharing a directory take a lock on
it for each write.

One session failing to fetch does not stop the others. A failed fetch is
noted, and the next run takes the sessions that have not failed first and the
ones that have last, the longest ago first: every session has its turn before
any has a second. After two failures in a row `fetch-due` also asks F1's
archive, and FastF1's mirror of it, for this season's index and last season's.
If any answers, the fault is with those sessions and the batch carries on; if
none does, the batch stops until the next run.

Retries are timed from when a session was last fetched, by the stamp of the
machine that fetched it. A stamp more than an hour ahead of this machine's
clock, or from before the session started, is not believed, and a session with
no believable stamp is fetched again at once.

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
answer: a driver it leaves out has no result and no laps to account for. An
answer from Jolpica is used only if it is whole and gives every driver a number
and a lap count; otherwise the session waits. A
session published short stays on the fetch stage's list however old it is,
because a result corrected months later can be what left it short.

The figures a snapshot is judged by were recorded when it was fetched. A build
measures the feeds again once it has loaded them, and if they are not what the
record says it writes the figures it measured beside the snapshot, as
`remeasured.json`, publishes nothing from that judgement and decides again.
Every reader of the archive is given a corrected snapshot with the corrected
figures, so the fetch stage, the choice of snapshot and the build always judge
the same thing.

A build also checks that the feeds it loaded are of the session its calendar
entry describes: the same kind of session, started within three days of the
entry's start by F1's own session information. A marker whose start time
pointed at another race would otherwise bring that race's round and result
with it.

A correction is written against the one that was read, so a build never
replaces one it has not seen, and one written by a newer pipeline version is
left alone, as a newer version's pointer is. That is among versions that
measure alike. A change to what a measurement holds takes a new measurement
version, and each has an object of its own (`remeasured.json` for version 2,
`remeasured-m3.json` for the next): code reads and writes its own version's
and no other, so it never has to believe, or stand aside for, figures it
cannot read. A pointer records which figures
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

In format 2 no artifact carries the round or the calendar's names: a page
takes them from the index. The calendar still reaches what is published
through the session's identity, which is in the manifest and the pointer and
whose start time is the calendar's. So a session is built again when its
calendar entry changes, and when the change does not reach its files the
build is the same generation, named as it is by its content, under a pointer
that records the new entry.

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

1. `curl -s $B/v2/index.json` lists the calendar, and the session has a
   `session_key` and `complete`.
2. `curl -si $B/v2/pointers/<key>.json` is a 200 with
   `cache-control: public, max-age=30, ...`. Its `generation` is 64 hex
   characters and equals `manifest.sha256`.
3. `curl -si $B/v2/generations/<key>/<generation>/manifest.json` is a 200, not a
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

The site still reads format 1. The build now publishes format 2 only, so the
frontend's reader has to move to `v2/` and to the types generated from the
schema before a newly built session appears on a page. Every page now loads
its data in the browser and the site builds without `frontend/public/data`,
but that directory is still in git, and the old build-time dashboard code it
fed is still in the tree, unreachable. Nothing runs `run` on a schedule yet.
See section 10 of the findings document for the state of each step.

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
