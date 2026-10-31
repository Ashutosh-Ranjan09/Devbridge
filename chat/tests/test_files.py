"""Shared files: the type is the bytes', the size is capped, bytes and names are sealed,
nothing is edited or deleted, and only a candidate answers a recruiter's request."""

from __future__ import annotations

import io
import sqlite3
import zipfile

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient

from chat.config import settings
from chat.files import DOCX, JPEG, PDF, PNG, clean_name, sniff
from chat.models import NewMessage, NewThread
from chat.store import NoFileError, NotAllowedError, Store, TooLargeError, UnsupportedFileError
from tests.conftest import KEY, THREAD


def docx(parts=("[Content_Types].xml", "word/document.xml")) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in parts:
            z.writestr(p, "<x/>")
    return buf.getvalue()


PDF_BYTES = b"%PDF-1.7\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n"


@pytest.mark.parametrize(("data", "mime"), [
    (PDF_BYTES, PDF),
    (b"\x89PNG\r\n\x1a\n" + b"\0" * 20, PNG),
    (b"\xff\xd8\xff\xe0" + b"\0" * 20, JPEG),
    (docx(), DOCX),
])
def test_the_four_types_are_known_by_their_bytes(data, mime):
    assert sniff(data) == mime


@pytest.mark.parametrize("data", [
    b"<!doctype html><script>alert(1)</script>",          # HTML, whatever it is named
    b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    b"MZ\x90\x00" + b"\0" * 20,                            # a Windows program
    docx(("readme.txt",)),                                 # a zip, but not a Word document
    b"PK\x03\x04 not really a zip",
    b"",
])
def test_anything_else_is_refused(data):
    assert sniff(data) is None


@pytest.mark.parametrize(("name", "clean"), [
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\asha\\degree.pdf", "degree.pdf"),
    ("deg\x00ree\n.pdf", "degree.pdf"),
    ("", "file"),
    ("x" * 300, "x" * 120),
])
def test_a_name_is_only_ever_a_name(name, clean):
    assert clean_name(name) == clean


@pytest.fixture
def opened(store: Store) -> Store:
    store.open_thread(THREAD)
    return store


def ask(store: Store, what: str = "Degree certificate", thread: str = "app_1"):
    return store.post(thread, NewMessage(sender="u_ravi", side="recruiter", body=what, kind="request"))


def test_a_file_round_trips_and_neither_its_bytes_nor_its_name_are_readable_at_rest(opened: Store):
    secret = PDF_BYTES + b"ASHA-AADHAAR-1234"
    m = opened.post_file("app_1", sender="u_asha", side="candidate", name="Asha_Aadhaar.pdf", data=secret)
    assert m.kind == "file" and m.file is not None and m.file.mime == PDF and m.file.size == len(secret)
    info, data = opened.file("app_1", m.file.id)
    assert (info.name, data) == ("Asha_Aadhaar.pdf", secret)
    opened.db.commit()
    stored = (opened.files_dir / m.file.id).read_bytes()
    assert b"AADHAAR" not in stored and b"%PDF" not in stored
    assert b"Aadhaar" not in opened.path.read_bytes()


def test_a_file_moved_to_another_thread_does_not_open(opened: Store):
    opened.open_thread(NewThread(thread_id="app_2", candidate="u_bo", org="org_pay", started_by="u_ravi"))
    m = opened.post_file("app_1", sender="u_asha", side="candidate", name="a.pdf", data=PDF_BYTES)
    assert m.file is not None
    with pytest.raises(NoFileError):
        opened.file("app_2", m.file.id)       # not this thread's
    sealed = (opened.files_dir / m.file.id).read_bytes()
    with pytest.raises(InvalidTag):
        opened.box.open(sealed, f"app_2|{m.file.id}|bytes")


def test_too_large_or_the_wrong_type_is_refused_and_nothing_is_kept(opened: Store, monkeypatch):
    monkeypatch.setattr(settings, "max_file_bytes", 100)
    with pytest.raises(TooLargeError):
        opened.post_file("app_1", sender="u_asha", side="candidate", name="big.pdf", data=PDF_BYTES + b"x" * 100)
    with pytest.raises(UnsupportedFileError):
        opened.post_file("app_1", sender="u_asha", side="candidate", name="cv.pdf", data=b"<html></html>")
    assert opened.messages("app_1") == [] and list(opened.files_dir.iterdir()) == []


def test_files_are_never_edited_or_deleted(opened: Store):
    m = opened.post_file("app_1", sender="u_asha", side="candidate", name="a.pdf", data=PDF_BYTES)
    assert m.file is not None
    with pytest.raises(sqlite3.IntegrityError, match="never edited"), opened.db:
        opened.db.execute("UPDATE files SET mime = 'text/html' WHERE id = ?", (m.file.id,))
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"), opened.db:
        opened.db.execute("DELETE FROM files WHERE id = ?", (m.file.id,))


def test_only_a_recruiter_asks_and_only_the_candidate_answers_in_the_same_chat(opened: Store):
    with pytest.raises(NotAllowedError):
        opened.post("app_1", NewMessage(sender="u_asha", side="candidate", body="send me yours", kind="request"))
    req = ask(opened)
    with pytest.raises(NotAllowedError):
        opened.post_file("app_1", sender="u_ravi", side="recruiter", name="a.pdf", data=PDF_BYTES, request_id=req.id)
    plain = opened.post("app_1", NewMessage(sender="u_ravi", side="recruiter", body="just text"))
    with pytest.raises(NotAllowedError):
        opened.post_file("app_1", sender="u_asha", side="candidate", name="a.pdf", data=PDF_BYTES, request_id=plain.id)
    opened.open_thread(NewThread(thread_id="app_2", candidate="u_bo", org="org_pay", started_by="u_ravi"))
    elsewhere = ask(opened, thread="app_2")
    with pytest.raises(NotAllowedError):
        opened.post_file("app_1", sender="u_asha", side="candidate", name="a.pdf", data=PDF_BYTES, request_id=elsewhere.id)
    front = opened.post_file("app_1", sender="u_asha", side="candidate", name="front.png",
                             data=b"\x89PNG\r\n\x1a\n" + b"\0" * 8, request_id=req.id)
    back = opened.post_file("app_1", sender="u_asha", side="candidate", name="back.png",
                            data=b"\x89PNG\r\n\x1a\n" + b"\1" * 8, request_id=req.id, note="the back")
    got = {m.id: m for m in opened.messages("app_1")}
    assert got[req.id].kind == "request" and got[req.id].body == "Degree certificate"
    assert got[front.id].request_id == req.id and got[back.id].body == "the back"
    assert got[back.id].file is not None and got[back.id].file.name == "back.png"


def test_a_database_from_before_files_is_upgraded_in_place(tmp_path, store: Store):
    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript("""
      CREATE TABLE threads (id TEXT PRIMARY KEY, candidate TEXT NOT NULL, org TEXT NOT NULL,
                            started_by TEXT NOT NULL, started_at TEXT NOT NULL);
      CREATE TABLE messages (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                             thread_id TEXT NOT NULL REFERENCES threads(id), sender TEXT NOT NULL,
                             side TEXT NOT NULL, body BLOB NOT NULL, sent_at TEXT NOT NULL);
      INSERT INTO threads VALUES ('app_1', 'u_asha', 'org_pay', 'u_ravi', '2026-11-01T00:00:00.000+00:00');
    """)
    old.execute("INSERT INTO messages (id, thread_id, sender, side, body, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("msg_old", "app_1", "u_ravi", "recruiter", store.box.seal(b"from before", "app_1|msg_old"),
                 "2026-11-01T00:00:01.000+00:00"))
    old.commit()
    old.close()
    upgraded = Store(tmp_path / "old.db", store.box)
    (m,) = upgraded.messages("app_1")
    assert (m.kind, m.body, m.file) == ("text", "from before", None)


# ── over HTTP ───────────────────────────────────────────────────────────────
def upload(client: TestClient, data: bytes, name: str = "degree.pdf", **fields: str):
    form = {"sender": "u_asha", "side": "candidate", **fields}
    return client.post("/v1/threads/app_1/files", headers=KEY, data=form, files={"file": (name, data, "application/pdf")})


def test_a_request_and_its_answer_over_http(client: TestClient):
    client.post("/v1/threads", headers=KEY, json=THREAD.model_dump())
    req = client.post("/v1/threads/app_1/messages", headers=KEY,
                      json={"sender": "u_ravi", "side": "recruiter", "body": "Degree certificate", "kind": "request"})
    assert req.status_code == 201 and req.json()["kind"] == "request"
    sent = upload(client, PDF_BYTES, request_id=req.json()["id"], note=" here it is ")
    assert sent.status_code == 201
    body = sent.json()
    assert body["request_id"] == req.json()["id"] and body["body"] == "here it is"
    got = client.get(f"/v1/threads/app_1/files/{body['file']['id']}", headers=KEY)
    assert got.status_code == 200 and got.content == PDF_BYTES
    assert got.headers["content-type"] == PDF and got.headers["x-file-name"] == "degree.pdf"


def test_refusals_over_http_say_why(client: TestClient, monkeypatch):
    client.post("/v1/threads", headers=KEY, json=THREAD.model_dump())
    assert upload(client, b"<html><script></script></html>", name="cv.pdf").json()["error"] == "unsupported_file"
    assert client.post("/v1/threads/app_9/files", headers=KEY, data={"sender": "u", "side": "candidate"},
                       files={"file": ("a.pdf", PDF_BYTES)}).status_code == 404
    monkeypatch.setattr(settings, "max_file_bytes", 10)
    assert upload(client, PDF_BYTES).status_code == 413
    asked = client.post("/v1/threads/app_1/messages", headers=KEY,
                        json={"sender": "u_asha", "side": "candidate", "body": "yours?", "kind": "request"})
    assert asked.status_code == 422 and asked.json()["error"] == "not_allowed"
    assert client.get("/v1/threads/app_1/files/file_nope", headers=KEY).status_code == 404
