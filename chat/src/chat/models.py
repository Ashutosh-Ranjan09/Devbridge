"""What crosses the HTTP surface. Ids are the web's: an application id names a thread, a
user id names a person. No name or email is ever sent here."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chat.config import settings

Side = Literal["candidate", "recruiter"]


class NewThread(BaseModel):
    thread_id: str = Field(min_length=1, max_length=64)    # the web's application id
    candidate: str = Field(min_length=1, max_length=64)    # who applied
    org: str = Field(min_length=1, max_length=64)          # the company whose recruiters may write
    started_by: str = Field(min_length=1, max_length=64)   # the recruiter opening it


class Thread(NewThread):
    started_at: str


class NewMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    sender: str = Field(min_length=1, max_length=64)
    side: Side
    body: str = Field(min_length=1, max_length=settings.max_body_chars)


class Message(BaseModel):
    seq: int            # this module's order; a stream resumes after the last one it sent
    id: str
    thread_id: str
    sender: str
    side: Side
    body: str
    sent_at: str


class ReadMark(BaseModel):
    reader: str = Field(min_length=1, max_length=64)
    side: Side
    seq: int = Field(ge=0)


class Seen(BaseModel):
    """The newest message each side has seen: by the candidate, or by any recruiter of the
    company. The other side's ✓✓."""
    candidate: int = 0
    recruiter: int = 0


class ThreadView(BaseModel):
    thread: Thread
    messages: list[Message]
    seen: Seen


class InboxRow(BaseModel):
    thread_id: str
    started_at: str
    last_at: str | None     # the newest message, None before the first
    unread: int             # the other side's messages after this reader's mark
