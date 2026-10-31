"""The parameters behind the published trace, for the tests that reproduce it.

docs/m6-worked-trace.html, docs/m6-decisions.html and the guide PDF were computed with
the APPROXIMATED Codeforces table (a 1495 peak at the 60th percentile, observing 0.739).
The live contract now holds the measured one, so those numbers are no longer what the
engine produces by default. A published artifact is never overwritten, so the tests that
check the engine still reproduces it run inside `published_trace()`, which points the
loader at the frozen table for their duration.
"""
from __future__ import annotations

import contextlib
import pathlib
from collections.abc import Iterator

APPROXIMATED = pathlib.Path(__file__).with_name("reference-distributions-approximated.yaml")


@contextlib.contextmanager
def published_trace() -> Iterator[None]:
    from m6_scoring import params

    saved = params.DEFAULT_DISTRIBUTIONS
    params.DEFAULT_DISTRIBUTIONS = APPROXIMATED
    params.default_parameters.cache_clear()
    try:
        yield
    finally:
        params.DEFAULT_DISTRIBUTIONS = saved
        params.default_parameters.cache_clear()
