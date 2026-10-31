"""The record: a recruiter opens a thread, nothing is edited or deleted, limits hold,
read marks only move forward, and an inbox shows only its own threads."""

from __future__ import annotations

import sqlite3

import pytest

from chat.config import settings
from chat.models import NewMessage, NewThread, ReadMark, Seen
from chat.store import NoThreadError, RateLimitedError, Store, ThreadConflictError
from tests.conftest import THREAD


def say(store: Store, body: str, *, side: str = "recruiter", sender: str | None = None, thread: str = "app_1"):
    who = sender or ("u_ravi" if side == "recruiter" else "u_asha")
    return store.post(thread, NewMessage(sender=who, side=side, body=body))  # type: ignore[arg-type]


def test_nobody_writes_to_a_thread_nobody_opened(store: Store):
    with pytest.raises(NoThreadError):
        say(store, "hello, I applied", side="candidate")


def test_opening_twice_is_one_thread_and_another_owner_is_refused(store: Store):
    first = store.open_thread(THREAD)
    assert store.open_thread(THREAD) == first
    with pytest.raises(ThreadConflictError):
        store.open_thread(NewThread(thread_id="app_1", candidate="u_bo", org="org_pay", started_by="u_ravi"))


def test_messages_are_never_edited_or_deleted(store: Store):
    store.open_thread(THREAD)
    m = say(store, "first")
    with pytest.raises(sqlite3.IntegrityError, match="never edited"), store.db:
        store.db.execute("UPDATE messages SET sender = 'x' WHERE id = ?", (m.id,))
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"), store.db:
        store.db.execute("DELETE FROM messages WHERE id = ?", (m.id,))


def test_messages_come_back_in_order_and_after_a_point(store: Store):
    store.open_thread(THREAD)
    a, b, c = say(store, "a"), say(store, "b", side="candidate"), say(store, "c")
    assert [m.body for m in store.messages("app_1")] == ["a", "b", "c"]
    assert [m.id for m in store.messages("app_1", after=a.seq)] == [b.id, c.id]


def test_one_person_is_limited_per_minute(store: Store, monkeypatch):
    monkeypatch.setattr(settings, "per_minute", 3)
    store.open_thread(THREAD)
    for i in range(3):
        say(store, f"m{i}")
    with pytest.raises(RateLimitedError):
        say(store, "one too many")
    say(store, "the other side is not limited by it", side="candidate")


def test_a_read_mark_moves_forward_only_and_never_past_the_newest(store: Store):
    store.open_thread(THREAD)
    a, b = say(store, "a"), say(store, "b")
    assert store.mark_read("app_1", ReadMark(reader="u_asha", side="candidate", seq=b.seq)) == Seen(candidate=b.seq)
    assert store.mark_read("app_1", ReadMark(reader="u_asha", side="candidate", seq=a.seq)).candidate == b.seq
    assert store.mark_read("app_1", ReadMark(reader="u_asha", side="candidate", seq=999)).candidate == b.seq


def test_seen_by_any_recruiter_of_the_company(store: Store):
    store.open_thread(THREAD)
    m = say(store, "question", side="candidate")
    store.mark_read("app_1", ReadMark(reader="u_meera", side="recruiter", seq=m.seq))
    assert store.seen("app_1").recruiter == m.seq


def test_an_inbox_counts_the_other_side_s_unread_and_shows_only_its_own_threads(store: Store):
    store.open_thread(THREAD)
    store.open_thread(NewThread(thread_id="app_2", candidate="u_bo", org="org_pay", started_by="u_ravi"))
    store.open_thread(NewThread(thread_id="app_3", candidate="u_asha", org="org_other", started_by="u_x"))
    say(store, "hi Asha")
    say(store, "my reply", side="candidate")      # her own message is not unread to her
    asha = store.inbox("u_asha", candidate="u_asha")
    assert {r.thread_id: r.unread for r in asha} == {"app_1": 1, "app_3": 0}
    assert asha[0].thread_id == "app_1", "newest first"
    ravi = store.inbox("u_ravi", orgs=["org_pay"])
    assert {r.thread_id: r.unread for r in ravi} == {"app_1": 1, "app_2": 0}
    assert store.inbox("u_ravi") == []
