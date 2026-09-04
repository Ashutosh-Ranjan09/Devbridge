"""Shared fixtures. The data and builders live in cvdata.py so test modules can
import them directly."""

from __future__ import annotations

import pytest

from tests.cvdata import DOCUMENT


@pytest.fixture
def document() -> str:
    return DOCUMENT
