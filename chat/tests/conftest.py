from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from chat import api
from chat.crypto import Box, load_key, new_key
from chat.models import NewThread
from chat.store import Store

KEY = {"Authorization": f"Bearer {api.API_KEY}"}
THREAD = NewThread(thread_id="app_1", candidate="u_asha", org="org_pay", started_by="u_ravi")


@pytest.fixture
def store(tmp_path) -> Iterator[Store]:
    s = Store(tmp_path / "chat.db", Box(load_key(new_key())))
    try:
        yield s
    finally:
        s.db.close()


@pytest.fixture
def client(store: Store) -> Iterator[TestClient]:
    api.app.dependency_overrides[api.store] = lambda: store
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()
