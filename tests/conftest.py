"""Shared fixtures. The data and builders live in cvdata.py so test modules can
import them directly."""

from __future__ import annotations

from pathlib import Path

import pytest

from cvv import cache
from tests.cvdata import DOCUMENT


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may read or write the project's response cache.

    Two failures, and the second is the one that bites. A test run would leave real
    entries in `.cache/http/` — fixture bodies indistinguishable from fetched ones,
    served to the next `cvv verify`. And within a run the tests became ORDER
    DEPENDENT: three LeetCode tests share the handle `ar009`, so the first one's
    mocked response was served to the rest and two of them stopped exercising
    anything. Both appeared the moment the LeetCode connector started caching.
    """
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "http")


@pytest.fixture
def document() -> str:
    return DOCUMENT
