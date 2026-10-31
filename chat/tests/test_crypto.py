"""Sealed at rest: the text is not in the file, and changed or moved bytes never open."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from chat.crypto import Box, MissingKeyError, load_key, new_key
from chat.models import NewMessage, NewThread
from chat.store import Store
from tests.conftest import THREAD


def test_a_message_round_trips_and_its_text_is_nowhere_in_the_database_file(store: Store):
    store.open_thread(THREAD)
    store.post("app_1", NewMessage(sender="u_ravi", side="recruiter", body="Your offer letter is attached"))
    assert [m.body for m in store.messages("app_1")] == ["Your offer letter is attached"]
    store.db.commit()
    raw = store.path.read_bytes()
    assert b"offer letter" not in raw and b"Your offer" not in raw


def test_a_changed_byte_never_opens():
    box = Box(load_key(new_key()))
    sealed = bytearray(box.seal(b"hello", "app_1|msg_1"))
    sealed[-1] ^= 1
    with pytest.raises(InvalidTag):
        box.open(bytes(sealed), "app_1|msg_1")


def test_a_row_moved_to_another_thread_never_opens(store: Store):
    """The ciphertext is bound to its thread and id: copied elsewhere, it fails rather
    than appearing in someone else's chat."""
    store.open_thread(THREAD)
    store.open_thread(NewThread(thread_id="app_2", candidate="u_bo", org="org_pay", started_by="u_ravi"))
    m = store.post("app_1", NewMessage(sender="u_ravi", side="recruiter", body="for Asha only"))
    (sealed,) = store.db.execute("SELECT body FROM messages WHERE id = ?", (m.id,)).fetchone()
    with pytest.raises(InvalidTag):
        store.box.open(sealed, f"app_2|{m.id}")


def test_another_key_cannot_read_the_messages(store: Store, tmp_path):
    store.open_thread(THREAD)
    store.post("app_1", NewMessage(sender="u_ravi", side="recruiter", body="hello"))
    store.db.commit()
    other = Store(store.path, Box(load_key(new_key())))
    with pytest.raises(InvalidTag):
        other.messages("app_1")


@pytest.mark.parametrize("key", [None, "", "not base64 !!", "c2hvcnQ="])
def test_no_usable_key_is_refused_rather_than_invented(key):
    with pytest.raises(MissingKeyError):
        load_key(key)
