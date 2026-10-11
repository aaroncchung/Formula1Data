"""The time limits and scope the job runs by, in one place.

These are decisions, not constants of nature. Where one comes from the plan
(docs/architecture-review-findings.md, section 8) the decision is named.
"""

from __future__ import annotations

from datetime import timedelta

# Decision 5: races and sprints first. Qualifying and practice follow once they
# have a view of their own.
IN_SCOPE_SESSION_TYPES = frozenset({"R", "S"})

# From a session's scheduled start to when its feeds are expected to be in
# F1's archive in full: the session itself, a margin for a red flag, and the
# time the archive takes to settle.
AVAILABLE_AFTER = {"R": timedelta(hours=4), "S": timedelta(hours=2)}
DEFAULT_AVAILABLE_AFTER = timedelta(hours=3)

# A session short of a bar is fetched again this often ...
RETRY_INTERVAL = timedelta(hours=6)
# ... for this long after its first fetch. Then it is published as partial
# (section 6, rule 6). Decision 6 allows 48 hours for a complete session when
# fetching runs on a local machine.
RETRY_WINDOW = timedelta(hours=48)
# After that it is still fetched, but rarely: F1 does repair its archive, and
# rule 3 lets fetching stop only for a session that is complete. The exception
# is a feed F1 has answered that it does not hold.
SLOW_RETRY_INTERVAL = timedelta(days=7)

# How long after a session its classification is still asked for on every run.
# Penalties and corrections land in the days after a race (AR-15); asking
# Jolpica about every session of every season on every run would not be polite.
CLASSIFICATION_RECHECK_WINDOW = timedelta(days=30)

# After that window a published session's classification is still asked for,
# on two days in every thirty, spread across sessions by their key: a result
# can be corrected months later, and "less often" must not become "never".
# `build --recheck` asks about every session at once.
SETTLED_RECHECK_EVERY_DAYS = 30
SETTLED_RECHECK_FOR_DAYS = 2

# A classification belongs to a session when its race date is this close to
# the session's start. A sprint is filed under the date of its Sunday race, and
# no two race weekends are less than a week apart.
CLASSIFICATION_DATE_TOLERANCE = timedelta(days=3)

# The feeds in a snapshot say when their session started. The calendar entry
# a build finds for the snapshot has to be of the same meeting: within this
# of that start. Calendar and F1 can disagree by hours and a postponement by a
# day; another meeting is a week away at the least.
SAME_MEETING_TOLERANCE = timedelta(days=3)

# How long a request made by FastF1, or beside it, may wait: to connect, and
# then between one piece of the answer and the next. FastF1 sets no limit of
# its own, so a connection that is accepted and then goes quiet would hold a
# run until whatever started it gives up on it. F1's largest feed is about
# 30 MB and arrives in seconds.
REQUEST_TIMEOUT_SECONDS = (30.0, 120.0)

# How long the fetch stage of a run of the whole job goes on starting new
# fetches. The build has to have its turn in every run: sessions that keep
# failing slowly would otherwise use the whole of the time the scheduler
# allows a run, on every run, and nothing already in the archive would be
# published. What is left over is fetched by the next run.
FETCH_STAGE_BUDGET = timedelta(minutes=60)

# After Jolpica has not answered this many times running, a stage stops
# asking it for the rest of the run.
NOT_ANSWERING_AFTER = 2

# A fetch that started this long ago and of which nothing more was noted is
# not still going: the run it was in has ended. Three times what the
# scheduler allows a run.
A_FETCH_IS_OVER_AFTER = timedelta(hours=6)

# What the spool's disk has to have free before a fetch is started. A race is
# about 200 MB in FastF1's cache, and as much again while it is packed.
SPOOL_NEEDS_FREE_BYTES = 2 * 1024**3

# A run of the whole job writes down when it finished. One that has not for
# this long has missed two turns of a six-hour schedule.
RUN_IS_OVERDUE_AFTER = timedelta(hours=13)

# A run that ends with something failed says so in the same place, and counts
# the runs that have done so one after another. One is said and let pass: F1
# refuses a fetch now and then, and the next run makes it good. This many
# running, which on a six-hour schedule is the same two turns, is a job that
# is failing, and is reported like one that has stopped.
THE_JOB_IS_FAILING_AFTER_RUNS = 2

# A fetch is stamped by the machine that made it. A stamp further ahead of
# this machine's clock than this was written by a clock that was wrong, and
# says nothing about when the fetch was made.
CLOCK_TOLERANCE = timedelta(hours=1)
