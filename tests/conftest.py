"""Shared fixtures. The data and builders live in cvdata.py so test modules can
import them directly."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from cvv import cache
from cvv.config import settings
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


@pytest.fixture(scope="session", autouse=True)
def warn_when_the_model_split_is_unpinned(request: pytest.FixtureRequest) -> None:
    """A live run with `CVV_NUM_GPU` unset is not reproducible, and it has failed.

    Ollama picks the GPU/CPU layer split from whatever VRAM is free AT LOAD TIME. In
    one session here the same machine reported 100% GPU and later 81%, and a live
    extraction assertion failed once in three runs while four consecutive runs inside
    a single model load were byte-identical. So the flake is the split moving, not
    the pipeline.

    This does not pin it — the right value depends on the card, and guessing one
    would be worse than saying so. It puts the cause at the top of the output, so the
    next person to see a live failure does not go looking for a bug in the extractor.
    """
    if request.config.getoption("-m") == "live" and settings.num_gpu is None:
        warnings.warn(
            "CVV_NUM_GPU is unset. Ollama picks the GPU/CPU layer split from free "
            "VRAM at load time, which is the one measured source of non-determinism "
            "here — a live extraction assertion has failed on it. Pin it (qwen3:1.7b "
            "has 28 blocks; `ollama ps` shows the current split) before treating a "
            "single live failure as a regression.",
            stacklevel=1,
        )


@pytest.fixture
def document() -> str:
    return DOCUMENT
