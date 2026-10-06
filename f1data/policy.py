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

# A fetch is stamped by the machine that made it. A stamp further ahead of
# this machine's clock than this was written by a clock that was wrong, and
# says nothing about when the fetch was made.
CLOCK_TOLERANCE = timedelta(hours=1)
