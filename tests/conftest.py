"""What every test has, whether or not it asks."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def a_spool_of_its_own(tmp_path_factory, monkeypatch):
    """A fetch is made in the spool, which by default is a directory of the user's own
    (f1data/spool.py). No test may leave a fetch there, or find one."""
    monkeypatch.setenv("F1DATA_SPOOL", str(tmp_path_factory.mktemp("spool")))
