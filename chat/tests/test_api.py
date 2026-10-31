"""Over HTTP: the key is required, a thread must be opened first, errors are one shape,
and the stream sends what was missed, then what happens."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from chat import api
from chat.models import NewMessage, ReadMark
from chat.store import Store
from tests.conftest import KEY, THREAD


def test_everything_but_health_needs_the_key(client: TestClient):
    assert client.get("/healthz").json() == {"ok": True, "encrypted_at_rest": True}
    assert client.post("/v1/threads", json=THREAD.model_dump()).status_code == 401
    assert client.get("/v1/threads/app_1", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_a_candidate_cannot_write_first(client: TestClient):
    r = client.post("/v1/threads/app_1/messages", headers=KEY,
                    json={"sender": "u_asha", "side": "candidate", "body": "hello?"})
    assert r.status_code == 404 and r.json()["error"] == "no_thread"


def test_a_conversation_over_http(client: TestClient):
    assert client.post("/v1/threads", headers=KEY, json=THREAD.model_dump()).status_code == 200
    sent = client.post("/v1/threads/app_1/messages", headers=KEY,
                       json={"sender": "u_ravi", "side": "recruiter", "body": "  Can we talk on Friday?  "})
    assert sent.status_code == 201 and sent.json()["body"] == "Can we talk on Friday?"
    client.post("/v1/threads/app_1/read", headers=KEY,
                json={"reader": "u_asha", "side": "candidate", "seq": sent.json()["seq"]})
    view = client.get("/v1/threads/app_1", headers=KEY).json()
    assert [m["body"] for m in view["messages"]] == ["Can we talk on Friday?"]
    assert view["seen"] == {"candidate": sent.json()["seq"], "recruiter": 0}


def test_an_empty_or_overlong_message_is_refused(client: TestClient):
    client.post("/v1/threads", headers=KEY, json=THREAD.model_dump())
    for body in ["   ", "x" * 4001]:
        r = client.post("/v1/threads/app_1/messages", headers=KEY,
                        json={"sender": "u_ravi", "side": "recruiter", "body": body})
        assert r.status_code == 422 and r.json()["error"] == "invalid_request"


def test_an_inbox_needs_exactly_one_scope(client: TestClient):
    assert client.get("/v1/inbox?reader=u", headers=KEY).status_code == 422
    assert client.get("/v1/inbox?reader=u&candidate=u&org=o", headers=KEY).status_code == 422
    assert client.get("/v1/inbox?reader=u&org=o&org=p", headers=KEY).json() == []


class OpenFor:
    """A request that disconnects after `n` checks."""

    def __init__(self, n: int) -> None:
        self.n = n

    async def is_disconnected(self) -> bool:
        self.n -= 1
        return self.n < 0


def test_the_stream_sends_what_was_missed_then_what_happens(store: Store, monkeypatch):
    monkeypatch.setattr(api.settings, "keepalive_seconds", 0.05)
    store.open_thread(THREAD)
    first = store.post("app_1", NewMessage(sender="u_ravi", side="recruiter", body="sent while away"))

    async def run() -> list[str]:
        chunks: list[str] = []
        gen = api.events(store, "app_1", 0, OpenFor(3))
        chunks.append(await anext(gen))                      # the backlog
        chunks.append(await anext(gen))                      # who has seen what
        store.post("app_1", NewMessage(sender="u_asha", side="candidate", body="back now"))
        api.hub.notify("app_1")
        chunks.append(await anext(gen))                      # woken, not polled
        store.mark_read("app_1", ReadMark(reader="u_ravi", side="recruiter", seq=first.seq + 1))
        api.hub.notify("app_1")
        chunks.append(await anext(gen))
        chunks.extend([c async for c in gen])
        return chunks

    chunks = asyncio.run(run())
    assert chunks[0].startswith(f"id: {first.seq}\nevent: message\n") and "sent while away" in chunks[0]
    assert chunks[1].startswith("event: seen")
    assert chunks[2].startswith(f"id: {first.seq + 1}\nevent: message\n") and "back now" in chunks[2]
    assert chunks[3].startswith("event: seen") and f'"recruiter": {first.seq + 1}' in chunks[3]


def test_a_stream_resumes_after_the_last_id_it_sent(store: Store):
    store.open_thread(THREAD)
    a = store.post("app_1", NewMessage(sender="u_ravi", side="recruiter", body="old"))
    store.post("app_1", NewMessage(sender="u_ravi", side="recruiter", body="new"))

    async def first_chunk() -> str:
        return await anext(api.events(store, "app_1", a.seq, OpenFor(1)))

    chunk = asyncio.run(first_chunk())
    assert "new" in chunk and "old" not in chunk
