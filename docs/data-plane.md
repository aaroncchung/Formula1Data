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
    http-cache.sqlite.gz       the raw HTTP responses; a build reads F1's car feed from them
    extra/PitStopSeries.jsonStream, extra/WeatherData.jsonStream, extra/circuit-info.json
    snapshot.json              written last; without it the snapshot does not exist
    remeasured.json            only where a build found the snapshot's record wrong
archive/legacy/<name>-<id>.tar.gz + .json         a whole directory, kept as it was
archive/attempts/<year>/<start>-<type>.json       the fetches made of that session, and how each ended
archive/runs/last.json                            when the whole job last finished, and on which machine

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

Only a race or a sprint is published. The archive can hold any session,
since `fetch` archives what it is asked for, and nothing is built of any
other: every file of a generation is written for a session that is raced.
Should a pointer to another kind of session be in the bucket, from a
publisher before this rule was kept, the build passes it over wherever it
counts what is published, the index leaves it out, and the site does not
open it, by its key or any other way. A session's kind is F1's name for it
in its own year: the sprint of 2021 was called Sprint Qualifying, which
since 2024 is the session that sets a sprint's grid.

## The published format

Every object under `v2/` has a model in `f1data/models.py`, and that file is
the contract. The files of a generation are built as their models and written
from them, so a field that is not declared cannot be published and a value of
the wrong kind stops the build. The envelopes around them (the manifest, the
pointer, the index and the standings) are written from dictionaries by the
publisher; their models say what shape they have, and a test holds a bucket
the publisher wrote against them (`tests/test_contract_fixture.py`). `python
-m f1data schema` writes the models out as
`schema/published-v2.schema.json`, which is what the frontend's types are
generated from. A test fails when the committed file and the models disagree.

A generation of a race is about 45 objects and 20 MB:

```text
summary.json  drivers.json  laps.json  results.json  stints.json  pit-stops.json
weather.json  race-control.json  corners.json  coverage.json  position-replay.json
analysis/<name>.json              nine analyses
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
- A lap's distance never goes backwards. FastF1's does, by a tenth of a
  metre, while a car stands in its pit box; each sample here has the furthest
  the car had been. A car at rest has many samples at one distance, so a
  reader that looks a sample up by distance has to say which of them it
  means (`frontend/src/lib/telemetry-compare.ts` matches time into one
  standstill with time into the other).
- Arrays that run side by side (a lap's channels, a driver's laps in the
  telemetry index, a car's frames in the replay) are of one length, and a
  file in which they are not is not published. The schema cannot say so; the
  models check it.
- F1's car feed sends 104, on a scale that ends at 100, for a pedal it has no
  reading of: most often both pedals at once, while it repeats the speed and
  engine speed it last had, and each by itself too. FastF1 passes the
  throttle on and makes the brake "on". Here a pedal F1 marked has no value
  (`null` in a published lap, and in what the analyses read): the throttle at
  a marked sample and between it and the samples either side, the brake from
  a marked sample until the next with a reading. The rest of the sample is as
  F1 sent it. The brake's mark cannot be seen in what FastF1 loads, so a
  build reads it from F1's raw car feed, which is among the raw responses
  kept with a snapshot (`http-cache.sqlite.gz`). If those are missing, cannot
  be read, or are not the feed FastF1's table was made from, the build says
  so and takes the brake to have no reading where the throttle has none,
  which misses the brake marked by itself. About four laps in a hundred have
  a marked stretch, most of them under two seconds; in the 2026 Hungarian GP
  it is 28% of the race. A "gear" over 8 is treated the same way: it is not
  a gear, and the lap has none there. In the corner analysis a driver's row
  says what the feed shows of its braking (`braking`): seen from where it
  began; none, with the brake read all the way in; begun in a stretch with
  no reading, so that the driver braked from a point that is not known; or
  not seen, with part of the approach unread, so that whether the driver
  braked is not known. Only the first has a brake point. A corner's braking
  is looked for in the corner's own stretch of the lap, from half-way back to
  the corner before to half-way on to the next: a braking is the corner's
  when the car is still slowing from it there, which it is until it has
  gathered 8 km/h from the slowest it has been, until the next braking
  begins, and no further than 250 m past where the brake came off. So one
  braking through two corners is in both rows, from the one brake point; one
  that begins past a corner, in its stretch, is in that corner's row, with a
  brake point after the corner's place; and a braking that has not taken
  8 km/h off the car by a corner's slowest point is not in its row. Each row
  says where its own lap has the
  corner (`corner_distance_m`), which is what the row's other distances are
  along; the corner's own `distance_m` is along the lap the corners were
  placed on, and another lap can have the corner tens of metres from there.
  A corner is where the lap's line passes within 50 m of it, between two
  samples where that is nearer than either, and of several passes the one
  where the corner should be along that lap, which is told
  from the corners the line passes once. A lap that went from line to line
  and is not seen at a corner (it ended down the pit entry, or its position
  feed froze) has no row for that corner, and the result names it.
- A driver's stints are consecutive runs of laps that never overlap. A lap
  with no compound stays with the set it is numbered with. F1 gives a car a
  new stint number when it goes through the pit lane, whether or not its
  tyres are changed; where its tyre data has the car on the same compound,
  one lap older, the lap stays in the stint it was in, and the numbers after
  it close up. So `stint` in `laps.json` is F1's number less the passages
  before it.
- A pit stop is the timing's entry to the pit lane with F1's own figures
  beside it, matched by driver and lap. F1's feed sends a stop once and then
  only what changes, so a stop is followed by its driver and its place in
  that driver's list, and a correction lands on the stop it corrects. It also
  sends some stops twice, under two places; a driver stops once on a lap, so
  those are one stop, here and in the count in `coverage.json`. F1
  sometimes reports a stop late and with no lap; such a report goes to the
  stop the timing shows the car finishing in the two minutes before it, when
  there is exactly one that no other report names and whose pit-lane time is
  the report's own, and is left out otherwise. A car in the pit lane while the
  session was red-flagged is marked `under_red_flag`, and the strategy
  analysis leaves its wait out of the pit-lane figures.
- Not every entry to the pit lane is a pit stop: a car serves a drive-through
  penalty, or the field follows the safety car down the pit lane. Each entry
  says whether the car went out on another set of tyres (`tyres_changed`,
  from the stints; null where F1's tyre data does not say). The strategy
  analysis and the site read an entry in one order. A car there while the
  session was red-flagged waited, whatever was done to it meanwhile. Else it
  made a stop when F1's pit-stop feed gives it a stationary time or its tyres
  were changed. Else it is taken for a passage when both feeds say so: no
  stationary time, and the same tyres afterwards. The pit-lane figures of the
  strategy analysis are of the stops the pit-stop feed reports and no other
  entry; its pit loss and its pace change across a driver's first stop leave
  out the waits and the passages. F1's tyre data can lag (by eight laps in
  the 2025 Miami GP), which is why it is never taken alone as word that a car
  did not stop.
- A driver is found by car number in every feed and named by F1's three
  letters, from the timing, the driver list or the classification. A driver
  none of them names is published under the car number as text. FastF1
  writes the word `None` where a code is missing; no reader takes that, or
  any other text, on trust (`f1data/loaded.py`).
- A weather reading is null where F1 sent none. FastF1 writes 0 for those, so
  the feed itself is archived with the session and asked; a fetch that loads
  the weather and cannot keep the feed's lines is not archived, and is made
  again. Snapshots taken before the feed was kept are published as FastF1 has
  them; every line of every one of those 51 sessions gives every reading. F1
  itself sends 0.0 for a sensor with no reading (the track temperature, twice
  each in the 2026 Azerbaijan and Bahrain GPs); a temperature or humidity of
  exactly zero between readings twenty or more away is published as null.
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
a session can measure correctly and still fail to build. It contacts neither
F1 nor Jolpica. Told a directory it needs no network at all; told `r2` it
reads the bucket, with the credentials in the environment (the tests do not
read `.env`). It runs when it is told where the archive is:

```text
F1DATA_TEST_ARCHIVE=<a directory store, or r2> python -m pytest tests/test_recorded_race.py -s
```

In PowerShell the variable is set first: `$env:F1DATA_TEST_ARCHIVE = "<...>"`.

After an intended change to what a build produces, record the golden file
again by adding `F1DATA_WRITE_FIXTURES=1`.

## Commands

All of them are `python -m f1data <command>`, from the repository root, with
`pip install -r requirements.txt`. `--store` is a directory or `r2`, and
defaults to the `F1DATA_STORE` environment variable.

| Command | What it does |
| --- | --- |
| `run` | The whole job: `build`, then `fetch-due`, then `build` again if anything was fetched. What a schedule runs |
| `last-run` | Say when `run` last finished on the machine that fetches, and how. Exits 1 when that is more than 13 hours ago or more than an hour from now, when it never has, or when its last two runs both failed. `--max-failed-runs N` for another count; `--allow-never` to let "never" pass |
| `fetch-due` | See through what is in the spool, then fetch every finished race and sprint the archive does not hold in full, of this year, last year and any year with a session still short. `--dry-run` to see the plan, `--limit N` to start at most N new fetches |
| `fetch --year Y --event E --session S` | Fetch one session as a new snapshot. Any session is archived; only a race or a sprint is ever built. `S` is given to FastF1 as it is written: a name such as `Sprint Shootout`, or `R`, `S`, `Q`, `SQ`, `SS`, `FP1` to `FP3` |
| `build` | Build and publish every archived race and sprint that needs it, then the index and standings. `--session-key K` to limit; `--shard I/N` to split across jobs |
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

A session is fetched into a spool on the machine (`%LOCALAPPDATA%\f1data\spool`,
or `~/.cache/f1data/spool`, or wherever `F1DATA_SPOOL` says), and stays there
until its snapshot's marker is in the archive (`f1data/spool.py`). Each fetch
has a directory there and a lock beside it. The run that makes the fetch
takes the lock before the directory exists and holds it until it is done with
it. Any other run takes the lock before it does anything to the directory,
and decides what to do by what the directory is then. The lock is the
operating system's and goes with the process: nothing is taken for abandoned
by its age, and two runs cannot both be at one fetch. The spool is the
program's own: a directory put there by anything else is removed once it is
an hour old.

What an earlier run left there, a run deals with before it asks F1 for
anything:

- a fetch that is whole and was not archived, because the upload failed, is
  uploaded. The run that fetched it said `FETCHED, NOT ARCHIVED` and exited 1;
- a session F1 served that could not be written down as whole, because the
  disk was full or the run was stopped at that moment, is read back from the
  fetch's own cache with every request refused, written down, and uploaded.
  Reading back asks nothing of F1 or of anyone else: FastF1 answers from its
  cache what it would otherwise ask again, however old that is. So what is
  archived is what that fetch was served, and it is stamped with the time the
  fetch ended. This is tried on every run until it works. Nothing the program
  does removes such a fetch, and its session is not asked of F1 again
  meanwhile; each run that cannot see it through says `a fetch that F1 served
  could still not be written down`, with the reason, and exits 1;
- a fetch that was stopped before F1 had served the session holds part of a
  session, as a failed fetch does. It is removed, and the session is fetched
  again from the start in its turn. A fetch is never carried on from where it
  stopped: a snapshot is of one fetch, made into an empty cache;
- a fetch another run holds is left to that run, and its session is not
  fetched meanwhile.

A fetch is for the store it was started for, which for `r2` is one account's
bucket: a run against another store leaves it as it is, and says how many it
left. The only fetches removed before they are archived are ones that did not
run to their end. A fetch that has is marked as served by renaming a file
that was made with its directory, which needs no room on the disk; should
that fail and writing it down fail too, the run says that a later run will
take it for part of a session.

A fetch is not started with less than 2 GB free where the spool is, by
`fetch`, `fetch-due` or `run`: a run says so, stops fetching, and exits 1.
(`probe` archives nothing and fetches into the temporary directory, which is
not looked at.) What is already in the
spool is still seen through, since uploading it is what makes room. Packing a
snapshot for upload, restoring one and building use the system's temporary
directory (`%TEMP%`, or wherever `TMP` says), which is not looked at and
wants as much room again as a session takes; if it is on another disk than
the spool, that disk has to have it.

The spool wants looking at by hand in two cases. A run says so each time,
and exits 1 for as long as either is there.

- A directory whose record cannot be read is named in a line that begins
  `ATTENTION`, with what is wrong with the record, and is left exactly as it
  is: nothing in it is read, uploaded or removed. Nothing is known of it, so
  its session is fetched again in its turn. Such a record is cut off, or was
  written by another version of this program than the one running. A
  directory is kept by the rules of the version that made it, its locks
  among them, so only records of the running version's form (schema 2) are
  acted on. Schema 1 was written only by commits of the rewrite branch on
  2026-10-07, before the job had run on any schedule. What to do with such
  a directory:
  - if the version that wrote it can still be run, stop the scheduled task,
    run that version once (`fetch-due`), and it sees its own fetches
    through;
  - otherwise keep the directory whole in the archive, where nothing reads
    it and nothing loses it, and then remove it: `python -m f1data
    archive-directory --path <the directory> --name spool-<its name in lower
    case>`, as in `--name spool-20261007t140000z-a1b2c3d4`. The command
    takes lower-case letters, digits and hyphens.

  That `fetch-due --dry-run` does not list a session does not show that the
  session is archived: it lists only what the job would fetch.
- A session F1 served that can still not be read back or written down stays,
  and holds its session back, until whatever the run reports is put right or
  the directory is removed. Removing it has the session fetched again.

One session failing to fetch does not stop the others. Each calendar entry
has a note of the fetches made of it (`archive/attempts/`). A fetch is noted
when it starts and again, under its own name, when it ends, so two runs
noting one session say the same in whichever order they write, and a fetch
seen through by a later run is the fetch that was begun. A fetch F1 served
is noted as having succeeded whether or not it has reached the archive yet.
A fetch that started and of which nothing more is noted has not succeeded:
it is still going, or its run ended under it, and the note cannot tell
which. For each entry a run counts the fetches that have not succeeded since
the last that did, in the order their words reached the note, and names the
entry at three in a line that begins `ATTENTION`. One that started before
that success and never ended is counted for six hours from its start, while
it may still be going, and not after. A note keeps the twelve latest fetches
of its entry. New fetches are taken in the order of when each session was last
tried, whether that fetch failed or arrived: the ones never tried first, then
the one tried longest ago. So the fetches a run starts reach every session
that is due before they reach any a second time, however the run is cut
short: by `--limit`, by its time, or because nothing answers.

Every request has a time limit. One that is made without a limit of its own,
as FastF1's to F1 are, is given 30 seconds to connect and two minutes without
a byte arriving; FastF1 gives its requests to Jolpica five seconds itself.
That stops a connection that goes quiet. It
does not bound an answer that keeps arriving slowly, and one fetch has no
limit of its own. So the fetch stage is given a time, an hour in `run` and
whatever `fetch-due --budget-minutes` says for a stage run by hand, and the
time is asked before everything the stage starts: an upload from the spool, a
reading back, a question to Jolpica, a fetch. What is left is for the next
run. After Jolpica has not answered twice running, a stage stops asking it
for the rest of the run: the fetch stage judges the sessions it has left by
what their snapshots recorded, and the build holds them. An answer that
there is no result yet is an answer. After two fetches in a row have failed,
`fetch-due` asks F1's archive, and FastF1's mirror of it, for this season's
index and last season's. If any answers, the fault is with those sessions
and the batch carries on; if none does, the batch stops until the next run.

`run` builds first. What the archive held when a run began is published
before the run asks anything of F1, so that nothing the fetch stage meets can
keep the build from its turn, run after run. If the fetch stage then put
anything in the archive, the run builds again.

Retries are timed from when a session was last fetched, by the stamp of the
machine that fetched it. A stamp more than an hour ahead of this machine's
clock, or more than an hour before the session started, is not believed, and a
session with no believable stamp is fetched again at once.

## Credentials

R2 is reached through its S3 API. The bucket has to exist: nothing here makes
one. Put these in `.env` at the repository root (it is ignored by git), or in
the environment:

```text
F1DATA_STORE=r2
R2_BUCKET=formula-1-data-artifacts
R2_ACCOUNT_ID=<Cloudflare account id>
R2_ACCESS_KEY_ID=<from an R2 API token with Object Read & Write on the bucket>
R2_SECRET_ACCESS_KEY=<from the same token>
```

`CLOUDFLARE_API_TOKEN` works in place of the key pair, which is how the
workflows publish with the secret the repository already has.

`.env` is for commands run on a machine. The workflows read the same names
from the repository's settings on GitHub, and a repository set up afresh
needs them there: the variable `R2_BUCKET`, the secret
`CLOUDFLARE_ACCOUNT_ID`, and either the secrets `R2_ACCESS_KEY_ID` and
`R2_SECRET_ACCESS_KEY` or the secret `CLOUDFLARE_API_TOKEN`. Deploying the
Worker needs `CLOUDFLARE_API_TOKEN` in any case, with permission to deploy
Workers: an R2 key pair cannot do that.

`.env` is read from the directory a command is run in, before anything else,
as UTF-8 lines of `NAME=value`. A variable already set in the environment is
left as it is. The scheduled task below sets its working directory to the
repository for this reason.

## Setting up a machine

On the machine that is to fetch, which has to be on a network F1 answers
(`python -m f1data probe --year 2026 --event 8 --session R` says whether it
is, and archives nothing):

1. Python 3.12, and a checkout of this branch on a local disk. Not in a
   folder a sync client manages (see "Running on a schedule").
2. A virtual environment outside the checkout, and the pinned packages in it:
   `py -3.12 -m venv C:\venvs\f1data`, then
   `C:\venvs\f1data\Scripts\python.exe -m pip install -r requirements.txt`
   from the checkout (`requirements-dev.txt` as well, to run the tests). The
   versions are pinned because a snapshot is FastF1's cache as that FastF1
   wrote it. Wherever this guide says `python`, it means that one: either
   `C:\venvs\f1data\Scripts\Activate.ps1` first, or the full path in place
   of the word. A bare `python` on a new Windows machine is another Python,
   or the Store's.
3. `.env` in the checkout, as above.
4. `python -m f1data fetch-due --dry-run` lists what would be fetched. It
   changes nothing in the bucket or the spool. It does read: the archive's
   markers and the published pointers, the calendars, and Jolpica for the
   sessions it has to judge; and it makes a scratch directory under the
   system's temporary one, which it removes.

The first run against an empty bucket has two seasons to fetch: every finished
race and sprint of this year and last, about fifty sessions, each some 200 MB
on disk while it is fetched and 100 MB in the bucket. `run` gives its fetch
stage an hour, so the scheduled job catches up over its first few runs
without being told to, building as it goes. To do it in one sitting instead:
`python -m f1data fetch-due` (no time limit unless `--budget-minutes` is
given), then `python -m f1data build`.

## Running on a schedule

Fetching has to run on a machine F1 answers, which rules out hosted runners
(decision 2 of the plan: a scheduled task on a local machine). With the
credentials above in `.env`, `python -m f1data run` is the whole job, and it is
safe to run as often as you like: it fetches only what is due and builds only
what changed. Every six hours is what the retry interval asks for, and is
plenty for the 48-hour bar.

On Windows, from an elevated PowerShell, with the two paths set to yours:

```powershell
$repo   = "C:\path\to\Formula1Data"
$python = "C:\path\to\venv\Scripts\python.exe"
$log    = "$env:LOCALAPPDATA\f1data\run.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

$action    = New-ScheduledTaskAction -Execute "cmd.exe" -WorkingDirectory $repo `
               -Argument "/c `"`"$python`" -m f1data run >> `"$log`" 2>&1`""
$trigger   = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
               -RepetitionInterval (New-TimeSpan -Hours 6)
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
               -ExecutionTimeLimit (New-TimeSpan -Hours 2) -WakeToRun `
               -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName "Formula1Data run" -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal
```

The principal is what makes it unattended. Registered without one, a task
runs only while its user is logged in: log out for the weekend and nothing
runs, and since Python never starts, nothing is logged either. `S4U` is "run
whether the user is logged on or not" without a stored password. A task run
that way cannot reach network shares, and files that a sync client has not
put on the disk are not there for it: keep the checkout, the virtual
environment and `.env` on a local disk outside OneDrive or the like.

`-StartWhenAvailable` runs a missed start when the machine comes back on, and
the job catches up on anything it missed, because F1's archive keeps past
sessions. The machine does not have to be on when a session finishes.
`-MultipleInstances IgnoreNew` keeps a second run from starting while one is
going; two at once would not lose anything, only fetch twice. Without the two
battery settings a laptop on battery does not start the task, and stops one
that is running when it is unplugged.

Before a new version of this program is put on the machine, disable the task
and let a run that is going finish (`Disable-ScheduledTask -TaskName
"Formula1Data run"`, and `Enable-ScheduledTask` after). Otherwise two versions
can be at work in one spool, each keeping it by its own rules.

The definition above builds with these cmdlets, but nothing has registered
the task yet, and it has not run on a schedule.

### Knowing that it ran

- **The log** is `%LOCALAPPDATA%\f1data\run.log`, in UTF-8, written a line at
  a time, so a run that is killed has still written what it printed. Each
  run starts with `[<time>] run started` and, unless it was killed, ends with
  `[<time>] run finished, exit <code>, <seconds> s`. Exit 1 means something
  failed: a fetch, an upload, a build. A line beginning `ATTENTION` names
  something that wants looking at: a session whose fetch keeps failing, or a
  directory of the spool that cannot be read. `FETCHED, NOT ARCHIVED` names a
  session that is waiting in the spool.
- **A run that did not happen** writes nothing, so it is looked for from
  outside: `python -m f1data last-run` reads `archive/runs/last.json` from the
  bucket and exits 1 when the last run finished more than 13 hours ago, or
  when no run has ever been written down. A run written down as finishing
  more than an hour from now fails too: the record is stamped by the clock
  of the machine that fetches, and one set ahead would otherwise vouch for
  the job until that time came round. Run it from any machine that can
  read the bucket. The publish workflow runs it every six hours once that
  workflow is on the default branch, which is where GitHub runs schedules
  from, so that a job that has stopped, or was never installed, turns a
  workflow red.
- **A run that happens and fails** is in the log, on a machine nobody is
  looking at. The record of a run says how it ended and how many runs have
  failed one after another, and `last-run` reads that too. One failed run is
  said (`DEGRADED`, and a warning on the workflow run) and let pass: F1
  refuses a fetch now and then, and the next run makes it good. Two running,
  which is the same two turns of the schedule, exit 1 (`FAILING`).
- **Two runs that end together**, the schedule's and one started by hand,
  both count from the record they read. Each writes the record only over the
  one it read, and the one that loses reads again, so two that fail are two
  failures. The record is of the run that ended last: a run that ended
  before the one written down leaves its times and exit code alone, and adds
  its own failure to a failure that followed it. Its success takes nothing
  off, so after such a pair the count can be one too high until a run works.
- **Before the job's first run** there is nothing for `last-run` to read, and
  the scheduled workflow fails. That is meant: a job that was never installed
  looks exactly like that. For the days between the workflow reaching the
  default branch and the first run, set the repository variable
  `F1DATA_FETCH_JOB_NOT_YET_RUN` to `true`, which lets "never" pass with a
  warning on every scheduled run, and remove it once the job has run.
- **The task itself:** `Get-ScheduledTaskInfo -TaskName "Formula1Data run"`
  gives the last run time and result. Task Scheduler's history says why a
  start was skipped, if history is enabled (it is off by default: "Enable All
  Tasks History" in Task Scheduler).
- **A session published as partial** is not a failure and exits 0. Its
  pointer has `complete: false` and what it is short of; the index has
  `complete: false`; the session's page says both.

## When a session counts as complete

`fetch` measures what arrived, per driver and per feed, and stores the figures
with the snapshot (`f1data/coverage.py`). A race or sprint is complete when:

- every feed arrived, the session status shows it ended, and Jolpica has its
  classification;
- every classified driver has at least the laps they are classified with;
- for each driver, 95% of those laps have car data, position data, and a tyre
  compound and stint. A lap counts for car or position data only if its samples
  run from the start of the lap to its end with no hole longer than 5 seconds;
- for each driver, no more laps repeat themselves than may be missing (5%).
  F1's car and position feeds can arrive on time and send the sample before
  again, as they do for most of the 2026 Hungarian GP: nothing is missing,
  and the speed stands still and the car stops on the map and jumps. A car
  sample repeats when it has the speed and the engine speed of the one
  before, a position sample when it has the place of the one before, and only
  samples of a car going faster than 30 km/h are counted, since a car in its
  pit box repeats itself truthfully. A car feed that stops at no speed would
  pass for that car, so the car feed's speed is not all that says a car is
  moving: the position feed does, where it has the car somewhere else within
  the second, and so does the timing, since a lap has room for standing only
  in what it took beyond the fastest lap of the session (and 5 seconds).
  Standing a lap had no room for is counted as the moving it was. What that
  leaves unseen is both feeds stopped together for less time than the lap
  had room for, as on a lap behind the safety car. A lap repeats itself when
  more than a quarter of those samples do. The two bars are `car_data_repeats` and
  `position_repeats`, and the session's page names the drivers and says that
  their telemetry, lap comparisons, track map and corner figures are not
  reliable;
- for each driver, 95% of those laps have car data, and position data, that
  can be relied on: no hole in them and not repeating themselves. The two
  tolerances above are not one each to spend. Two laps of forty missing and
  two others repeating meet both, with 36 laps to rely on where 38 is the
  bar; the driver is then short on `car_data` or `position`, and the pointer
  says how many laps of each kind;
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

An answer that Jolpica has no result has the session wait as well, until its
retry window has closed. A session already published with a result then
keeps it: built without one, it would have the order on track in place of
the result. One never published with a result is published as partial once
the window has closed, with every driver short of the classification. The
laps a snapshot recorded as classified are what Jolpica had on the day it
was fetched, so they are not what it is judged by.

The figures a snapshot is judged by were recorded when it was fetched. A build
measures the feeds again once it has loaded them, and if they are not what the
record says it writes the figures it measured beside the snapshot, as
`remeasured.json`, publishes nothing from that judgement and decides again.
Every reader of the archive is given a corrected snapshot with the corrected
figures, so the fetch stage, the choice of snapshot and the build always judge
the same thing.

A figure that was not counted when a snapshot was fetched, and can be counted
from its feeds, reaches the record the same way. The laps that repeat
themselves are such a figure: no session is fetched again for them. Until a
build has counted them the record says nothing of them, and they are not held
against it. The laps a feed can be relied on for, those with no hole in them
that do not repeat themselves, are another: the bar on them and the choice
between two snapshots read them. A record without them is not held to the
bar, and for the choice has every lap that repeats taken off its usable ones,
which is too few where a lap is bad both ways. So that the choice is not made
on that guess, a build counts these figures for every snapshot of the session
whose record lacks them, not only for the one it took, before it makes
anything of that one, and then decides again. A snapshot is loaded for this
once; one that will not load is left as its record has it, with a warning,
and does not stop the build of the one that was taken.

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
lost write, and whenever `build --recheck` is given. One published without a
result is asked about on every run until Jolpica has one.

## Workflows

| Workflow | Runs | Purpose |
| --- | --- | --- |
| `publish.yml` | Every six hours and manually, once it is on the default branch; until then on a push to `rewrite/data-plane` that touches it or `f1data/layout.py`, where the pipeline version is | `build` against R2, in four parallel parts. On a schedule it also runs `last-run` |
| `deploy-data-worker.yml` | Manually, and on a push to `main` that touches the Worker | Tests and deploys `formula-1-data-read` |
| `r2-contract.yml` | Manually, and on a push to the rewrite branch that touches the store | The store's tests against the real bucket |
| `probe-f1-access.yml` | Manually, and on a push to the rewrite branch that touches it | Whether F1 answers a hosted runner yet |
| `upload-archive-spool.yml` | Manually, and on a push to the rewrite branch that touches it | Stopgap: copies a fetch made without R2 credentials into the bucket. Delete it once the fetch machine has credentials |

A schedule runs a workflow as it is on the default branch, and a workflow can
be started by hand only once it is on the default branch (it can then be run
against another). That is why each has a push trigger while this work is on a
branch.

## Checking a publication

After a `build`, with `B=https://formula-1-data-read.aaronchenxi2.workers.dev/data`
(in PowerShell: `$B = "https://..."`, and `curl.exe` in place of `curl`, which
there is another command's alias):

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

Nothing runs `run` on a schedule yet: fetching is done by hand until the
scheduled task above is registered on a machine that has R2 credentials. The
old path (the old Worker, `pipeline/`, the ingestion workflows) is still in
the tree and still what `main` deploys; the plan removes it only after the
new one has carried three race weekends unattended. See section 10 of the
findings document for the state of each step.

## The pages

Every page reads the published data at runtime, from the base URL in
`NEXT_PUBLIC_PUBLISHED_DATA_BASE_URL`.

| Page | Address | Reads |
| --- | --- | --- |
| Home | `/` | The index, then the latest published session's summary files |
| Seasons, season, meeting, circuits | `/seasons`, `/season?year=`, `/meeting?year=&round=`, `/circuits` | The index only |
| Session | `/session?key=<session key>` | The index and the pointer, then each tab's files when the tab is opened |
| Strategy, telemetry, drivers, teams | `/strategy?key=`, and so on | One session's files; the latest published session when no key is given |
| Standings | `/standings?year=` | The index and `v2/standings/<year>.json` |

A session is linked by its key. `/session?year=&round=&session=` still opens
one, and the page then offers the link by key, since a round moves when the
calendar changes. A meeting is linked by F1's meeting key where the index
has one (`/meeting?key=`), and by year and round until one of its sessions is
published.

The site's types are generated from `schema/published-v2.schema.json`
(`npm run types` in `frontend/`, which writes
`frontend/src/lib/published/schema.ts`). A test fails when the committed file
is not what the generator makes of the schema, so a change to a published
shape has to be made on both sides in one commit.

### Working on the site without the network

No data is committed with the site. By default it reads the deployed Worker,
which is public and read-only. For work offline, or against data that does
not change:

```text
python -m tests.sample_bucket .sample --serve
```

writes a small made-up race in the published layout (three drivers, twelve
laps, every file a real race has, about 600 kB) and serves it as the Worker
does at `http://localhost:8788/data`. Put
`NEXT_PUBLIC_PUBLISHED_DATA_BASE_URL=http://localhost:8788/data` in
`frontend/.env.local`; the sample race is at `/session?key=9001`. It is made
by the publisher's own code from the session the tests are built on
(`tests/race.py`), and it is a partial session on purpose: one driver's tyre
data is short, so the page shows what a partial publication looks like.
