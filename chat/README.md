# DevBridge chat

One thread per application, between a candidate and the recruiters of the company they
applied to. A recruiter opens it; the candidate replies. A recruiter can ask for a
document and either side can share a file (PDF, PNG, JPG or DOCX, known by its bytes, at
most 10 MB). Messages and files are encrypted at rest (AES-256-GCM, key in `chat/.env`),
never edited or deleted, and arrive live over Server-Sent Events, relayed by the web.

```
uv sync
echo "CHAT_ENCRYPTION_KEY=$(uv run chat keygen)" > .env   # or let ../scripts/dev.sh write it
uv run chat serve                # :8090
uv run pytest                    # 46 tests
```

Encrypted at rest, not end to end: a copy of the database is unreadable without the key,
but this service decrypts to answer the web. See `CLAUDE.md` for the rules and the API.
