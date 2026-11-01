# m6_ingestor — evidence ingestor

**Status: complete (v1.0.0).** M6 submodule 6.2.

The plan's brief: *validation, idempotency, immutable persistence, quarantine for
unknown skills. No modelling.* (It also listed consent refusal; consent was removed
as out of scope for this project.) This module never
computes a score, applies a decay, or decides what evidence is worth. It decides
only whether a batch may enter the log, and records what it did.

```python
from m6_ingestor import EventLog, Ingestor
with EventLog("evidence.db") as log:
    receipt = Ingestor(log).ingest(batch)
```

```
python3 -m m6_ingestor serve  --db evidence.db --port 8100
python3 -m m6_ingestor ingest batch.json --db evidence.db
make ingest      # project the golden report and push it through
make test        # every suite, no pytest required
```

Stdlib only — `sqlite3` and `http.server` — except `yaml` and `jsonschema`,
which are already used elsewhere in the repo.

## Endpoints

| | |
|---|---|
| `POST /evidence/batch` | Ingest one batch. `202` with a receipt. |
| `GET /health` | Liveness, event count, ontology version in force. |
| `GET /events` | The log in fold order. `?subject=`, `?skill=`, `?skill=…&all` to include quarantined. |
| `GET /quarantine` | What is being held out of scoring, and which skills caused it. |
| `GET /batches` | What has been ingested, with each batch's `not_emitted[]`. |

The error type **is** the status code, and the distinctions are the contract:
`400` the producer is wrong, `409` two different events claim one identity.

## Storage

SQLite, because there is no package manager here. The SQL is kept to the subset
Postgres also accepts, so the agreed Postgres is a driver swap and a type-name
pass rather than a rewrite. Four tables: `batch`, `evidence_event`, a
denormalised `event_skill` so 6.3 can fold one skill without parsing every
document, and `cv_report`.

**One CV per developer.** `cv_report` records each completed CV report the facade
ingests (`M6.ingest_report`): whose, and M5's own time of the check (`valid_as_of`,
normalised to one UTC spelling so instants compare as text). The view `replaced_cv`
names every report a newer check of the same developer's CV has replaced — newest
by M5's clock, however late a report arrives; the id breaks a tie. The three read
paths (`events`, `events_for_skill`, `resolved_skills`) skip a replaced report's
evidence, so every score, explanation, search and shortlist sees only the current CV
and every assessment result (which never comes from a CV report). Nothing is
deleted: `events(include_replaced=True)` still returns it, and explain lists it as
"replaced by a newer CV". A FAILED check is not recorded, so an unreadable upload
never replaces a CV that worked. Rows are added only; triggers refuse the rest.

**Immutability is enforced by TRIGGER**, not by the absence of an `update()`
method. O4 recomputes every score by folding this log, so a row that quietly
changes rewrites history — and a rule that lives only in application code is one
careless migration away from not existing. The tests attack the database
directly to prove it.

## Three decisions worth knowing about

**A changed replay is a conflict, not an update.** `event_id` is
`sha256(verification_id, kind, discriminator)` — identity derived from what the
evidence is *about*, not what it says. Identical content under a known id is a
delivery artefact and a no-op. *Different* content under a known id means the
projection changed its mind about the same evidence, which is what a bug fix
looks like from here. History is not rewritten to accommodate it; a human decides
whether to re-project under a new `verification_id`.

**Quarantine is per skill, not per event.** An event naming three skills where
one is unknown still contributes to the two that are known. The event is stored
verbatim and flagged, so it is waiting when 6.1 adds the node — dropping it would
lose evidence the ontology has merely not caught up with, and scoring it would
invent a node nobody defined.

**The ontology is a two-method port.** `knows()` and `ontology_version`, nothing
more — the ingestor has no business traversing edges, and giving it access would
invite the modelling the plan explicitly excludes. The graph itself belongs to
6.1 (`m6_ontology`) and is imported from there, never re-exported from here;
`AcceptAll` is the escape hatch. Every receipt records which ontology judged it,
because a quarantine decision is only interpretable against a version.

## Tests — 64 in this package

| file | covers |
|---|---|
| `test_validation.py` | Schema re-checked at the boundary; batch-level uniqueness the schema cannot express; a rejected batch writes nothing; errors name *where*. |
| `test_idempotency.py` | Replay is a no-op; key order doesn't defeat dedupe; a known event in a new batch is a duplicate; a bug-fixed event is a conflict. |
| `test_persistence.py` | Triggers attacked directly; batch atomicity; fold order stable regardless of arrival order; survives reopening. |
| `test_quarantine.py` | Held not dropped, stored verbatim, excluded from scoring reads, per-skill not per-event, ontology swappable. |
| `test_api.py` | Real sockets, real status codes — plus **eight clients racing the same batch**, which is what found the two concurrency bugs below. |
| `test_end_to_end.py` | Report → projection → ingest → fold reproduces the published skill graph; replay changes no score. |

Two production bugs the concurrency test found, both fixed:

1. The connection was thread-bound while the server is threaded. A shared
   `sqlite3` connection raises `InterfaceError` under concurrent use — **reads
   included**, not only writes — so all access is serialised on one re-entrant
   lock.
2. `ingest()` was check-then-act. Locking only the write left two threads free to
   both observe an absent batch and both proceed, turning a replay into a
   primary-key collision. The whole decision is now held exclusively.

## Handing off to 6.3

`log.events_for_skill(skill)` returns exactly what the fold needs, in
`(occurred_at, event_id)` order, quarantined skills already excluded. A test
asserts that folding one skill this way gives the same score as folding the whole
log, so the narrow read is safe to optimise on. Tier lookup lives on
`SeedOntology.tier()` against the same seed file — one contract, two readers.
