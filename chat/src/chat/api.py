"""The HTTP surface the web calls. The browser never reaches it: the web checks who a
person is and whether they are on a thread, then calls here with the module's key.

Thin, like assessment's: who may open a thread is the web's check AND this module's (a
message to a thread nobody opened is a 404, so a candidate cannot write first); limits
and the record's immutability live in the store.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from chat.config import settings
from chat.crypto import Box, load_key
from chat.hub import Hub
from chat.models import InboxRow, Message, NewMessage, NewThread, ReadMark, Seen, Thread, ThreadView
from chat.store import NoThreadError, RateLimitedError, Store, ThreadConflictError

app = FastAPI(title="DevBridge chat", version="1.0.0",
              description="One thread per application. A recruiter opens it; messages are sealed at rest.")

# Generated when unset and printed by `chat serve`, as the other modules do.
API_KEY = settings.api_key or secrets.token_urlsafe(24)
hub = Hub()
_store: Store | None = None


def store() -> Store:
    """One store for the process: the streams and the posts must share it."""
    global _store
    if _store is None:
        _store = Store(settings.db_path, Box(load_key(settings.encryption_key)))
    return _store


class RefusedError(Exception):
    """Any answer that is not a 2xx. Flat, like the other modules': {"error", "detail"}."""

    def __init__(self, status: int, error: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.error, self.detail = status, error, detail


@app.exception_handler(RefusedError)
def _refused(_: Request, exc: RefusedError) -> JSONResponse:
    return JSONResponse({"error": exc.error, "detail": exc.detail}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
    why = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    return JSONResponse({"error": "invalid_request", "detail": why}, status_code=422)


def authorise(authorization: Annotated[str | None, Header()] = None) -> None:
    """Bearer token, compared in constant time."""
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not supplied or not secrets.compare_digest(supplied, API_KEY):
        raise RefusedError(401, "unauthorised", "Supply the API key as `Authorization: Bearer <key>`.")


Auth = [Depends(authorise)]
S = Annotated[Store, Depends(store)]


def _no_thread(thread_id: str) -> RefusedError:
    return RefusedError(404, "no_thread", f"No chat {thread_id}: a recruiter opens it first.")


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "encrypted_at_rest": True}


@app.post("/v1/threads", dependencies=Auth)
def open_thread(new: NewThread, s: S) -> Thread:
    try:
        return s.open_thread(new)
    except ThreadConflictError as exc:
        raise RefusedError(409, "thread_conflict", str(exc)) from exc


@app.get("/v1/threads/{thread_id}", dependencies=Auth)
def thread(thread_id: str, s: S, after: int = 0) -> ThreadView:
    t = s.thread(thread_id)
    if t is None:
        raise _no_thread(thread_id)
    return ThreadView(thread=t, messages=s.messages(thread_id, after), seen=s.seen(thread_id))


@app.post("/v1/threads/{thread_id}/messages", dependencies=Auth, status_code=201)
async def post(thread_id: str, new: NewMessage, s: S) -> Message:
    try:
        message = s.post(thread_id, new)
    except NoThreadError as exc:
        raise _no_thread(thread_id) from exc
    except RateLimitedError as exc:
        raise RefusedError(429, "rate_limited", str(exc)) from exc
    hub.notify(thread_id)
    return message


@app.post("/v1/threads/{thread_id}/read", dependencies=Auth)
async def read(thread_id: str, mark: ReadMark, s: S) -> Seen:
    try:
        seen = s.mark_read(thread_id, mark)
    except NoThreadError as exc:
        raise _no_thread(thread_id) from exc
    hub.notify(thread_id)
    return seen


@app.get("/v1/inbox", dependencies=Auth)
def inbox(s: S, reader: str, candidate: str | None = None,
          org: Annotated[list[str] | None, Query()] = None) -> list[InboxRow]:
    if (candidate is None) == (not org):
        raise RefusedError(422, "invalid_request", "Give either `candidate` or one or more `org`.")
    return s.inbox(reader, candidate=candidate, orgs=org)


class Disconnects(Protocol):
    async def is_disconnected(self) -> bool: ...


async def events(s: Store, thread_id: str, after: int, request: Disconnects) -> AsyncIterator[str]:
    """Everything after `after`, then each new message and read mark as it happens. The
    browser reconnects with Last-Event-ID, so a dropped connection loses nothing."""
    seen: Seen | None = None
    with hub.listen(thread_id) as wake:
        while not await request.is_disconnected():
            wake.clear()            # before reading, so a post in between still wakes us
            for m in s.messages(thread_id, after):
                yield f"id: {m.seq}\nevent: message\ndata: {m.model_dump_json()}\n\n"
                after = m.seq
            if (now := s.seen(thread_id)) != seen:
                seen = now
                yield f"event: seen\ndata: {json.dumps(now.model_dump())}\n\n"
            try:
                await asyncio.wait_for(wake.wait(), settings.keepalive_seconds)
            except TimeoutError:
                yield ": keep-alive\n\n"


@app.get("/v1/threads/{thread_id}/events", dependencies=Auth)
def stream(thread_id: str, request: Request, s: S, after: int = 0) -> StreamingResponse:
    if s.thread(thread_id) is None:
        raise _no_thread(thread_id)
    return StreamingResponse(events(s, thread_id, after, request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
