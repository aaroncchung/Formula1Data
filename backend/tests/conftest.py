"""Make the repository root and ``backend/`` importable for every test module.

Most test files insert these paths themselves at import time, but
``test_schedule_ingestion.py`` does not -- it resolved ``pipeline`` only
because an alphabetically-earlier sibling (``test_backfill.py``) had already
mutated ``sys.path`` as a side effect of being collected first. That made the
suite pass in aggregate while failing whenever the file was run on its own::

    pytest backend/tests/test_schedule_ingestion.py
    ModuleNotFoundError: No module named 'pipeline'

pytest imports conftest before collecting any test module, so doing it once
here removes the ordering dependency. The per-file inserts are left in place
deliberately: they keep ``python backend/tests/test_x.py`` working, which
conftest cannot cover because it is a pytest-only hook.
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent

for _path in (REPOSITORY_ROOT, BACKEND_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
