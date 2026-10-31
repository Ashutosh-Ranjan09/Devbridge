# cvv — CV Verification Engine

Verifies developer CVs against the systems the candidate names: GitHub, Codeforces,
LeetCode, CodeChef, live deployments. Extracts typed claims with verbatim spans, gathers
evidence, runs deterministic checks, and emits findings with provenance.

**It produces no score and no verdict.** It reports evidence and says explicitly what
it could not check. A person decides what any of it means.

> DevBridge M5. Built against the contracts in `../schemas/`, which M6 (`../skill-graph/`) reads too.

---

## Why there is no score

A single number invites a threshold, a threshold becomes a filter, and a filter
rejects people for reasons nobody can inspect. `FindingsReport` has no
`overall_score` field and that is deliberate.

Instead a report sorts into five buckets, and the fifth is the one that makes the
rest honest:

| | |
|---|---|
| ✓ **verified** | checked against an outside source, no discrepancy |
| ✗ **contradicted** | the source disagrees with the CV |
| ? **needs context** | worth a question — always printed with its innocent reading |
| – **not evaluated** | the check could not run, **and why** |
| □ **out of scope** | named as unverifiable, so nobody assumes otherwise |

A check that cannot run **abstains with a typed reason**. Silence would read as a
pass, and that is the failure this system exists to avoid.

---

## Quickstart

Needs Python 3.12, [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com)
running locally.

```bash
uv sync
ollama pull qwen3:1.7b

uv run cvv verify path/to/cv.pdf
```

That runs offline apart from the connectors. Nothing leaves the machine except public
API calls to the accounts the CV itself names.

```bash
uv run cvv verify cv.pdf --offline      # document-intrinsic checks only, no network
uv run cvv verify cv.pdf --brief        # add a model-written briefing
uv run cvv verify cv.pdf --worksheet    # what a human still has to do
uv run cvv verify cv.pdf --json         # the findings, as JSON
uv run cvv verify cv.pdf --save out/    # every stage, and the report M6 reads
uv run cvv evaluate cv.pdf              # corrupt one fact and see what notices
uv run cvv gold                         # extraction against hand-labelled claims (data/gold/)
uv run cvv rules                        # the live check catalogue
uv run cvv aliases                      # what the model decided skill names mean
uv run cvv inspect cv.pdf               # read a document without calling a model
```

### Optional

```bash
uv sync --extra ocr                     # scanned PDFs (~100 MB of model weights)
export CVV_GITHUB_TOKEN=...             # 60 → 5000 API requests an hour
export CVV_DATABASE_URL=postgresql:///cvv
export CVV_LLM_BACKEND=claude-code      # Claude via the local Claude Code wrapper
                                        # (+ CVV_CLAUDE_CODE_API_KEY, _MODEL, _URL)
```

`ollama` is the default backend: local, seeded, reproducible. `claude-code` is faster
and cleaner on the reference CV, has no seed, and records itself in the report's
`model_id`, so a stored report always says which model produced it.

Configuration lives in `.env` (prefix `CVV_`); `.env.example` documents every setting
and what leaving it unset actually means. **`CVV_GITHUB_TOKEN` is the operator's
token, never the candidate's** — asking a candidate for a personal access token is a
phishing pattern, and nothing here needs one.

---

## What it checks

29 of a catalogue of 41 — every one in scope. Seven are human by design, one is
excluded on fairness grounds, and the four credential checks are out of scope for this
project.

| Group | Built | What it reads |
|---|---:|---|
| **D** document-intrinsic | 11/11 | the CV alone — dates, roll number, internal contradictions |
| **G** GitHub | 10/10 | REST + the GraphQL contributions calendar |
| **P** platforms | 6/6 | Codeforces and LeetCode public APIs; CodeChef's profile page, scraped |
| **W** deployments | 1/2 | an HTTP request, and the repo's declared homepage — W2 is human |
| **C** credentials | 1/5 | the narrative; C1–C4 out of scope |
| **H** human | 0/6 | — by design; `--worksheet` prepares them |

CodeChef publishes no API, so its numbers come from the public profile page and are
marked as scraped. Its check (P5) can therefore only ever raise a question, never a
contradiction, and a page it cannot recognise is reported as a gap rather than read
as an empty profile.

The eleven **D** checks need no network at all. That is the invariant: *a CV from
someone with no account, no repositories and no contest history must still produce a
complete, honest report.* `--offline` is that path, and a test asserts every rule
still appears with its reason.

### Deliberately not built

- **Entrance-rank vs. cutoff** — JEE cutoffs vary by reservation category, and a
  category-blind comparison systematically flags reserved-category candidates for a
  rank that is entirely valid.
- **AI-generated-CV detection** — using a model to write a CV is not fraud, and
  detection penalises non-native English speakers hardest.
- **Contribution-authenticity scoring** — 400 one-line commits is a cron job and is
  also the atomic-commit habit the industry teaches. No threshold separates them, and
  the check tests no claim the CV ever made.
- **Identity, employment, degree and CGPA verification** — no accessible source. A
  degree can only be confirmed by the institution that awarded it.

---

## How it is measured

Unit tests prove each rule does what its author intended, using fixtures that author
wrote. They cannot prove the system catches a falsified CV. So:

```bash
uv run cvv evaluate cv.pdf --save-baseline out/
```

takes a real document, corrupts exactly one fact, and asks whether the check
responsible notices.

| | student CV | synthetic CV ¹ | professional CV ¹ |
|---|---|---|---|
| **detection** | 18/18 | 7/7 of applicable | 2/2 of applicable |
| **collateral** | 0 | 1 (correct) | 0 |

¹ measured 15 September, before the CodeChef check and the October fairness fixes.

**Collateral** — rules firing on a mutation they had no business noticing — is the
number that matters. It started at 2, and both were real bugs: one would have
contradicted an honest CV decisively, and neither was visible to 294 passing tests.

---

## Feeding the skill graph

`--save DIR` writes four files; `verification-report.json` is the contract's
`VerificationReport`, and it is all M6 (`../skill-graph`) needs:

```bash
uv run cvv verify cv.pdf --save out/
cd ../skill-graph
PYTHONPATH=packages python3 -m m6_projection ../cv-verification/out/verification-report.json --out batch.json
PYTHONPATH=packages python3 -m m6_ingestor ingest batch.json --db evidence.db
PYTHONPATH=packages python3 -m m6_query skills --db evidence.db
```

This module reports evidence; M6 decides what it is worth for each skill. The API's
`GET /v1/verifications/{id}` returns the same object.

---

## Using it as a service

```bash
uv run cvv serve
```

```
POST /v1/verifications              202 · Idempotency-Key honoured
GET  /v1/verifications/{id}         200 report · 202 while running
GET  /v1/verifications/{id}/claims/{claim_id}/provenance
GET  /v1/rules · /healthz · /readyz · /v1/usage
POST /v1/narrate · /v1/evaluate
```

Interactive docs at `http://127.0.0.1:8080/docs` — port 8080, because the Claude Code
wrapper has 8000. Binds to localhost — exposing it takes a deliberate `--host`. An
unset `CVV_API_KEY` generates one per run and prints it.

Two endpoints are restricted on purpose: **`/v1/narrate` accepts only a
`FindingsReport`** and **`/v1/evaluate` only a `ClaimGraph`**. Neither can reach the
document, so neither can leak it — enforced by the signature rather than by a prompt.

---

## How it works

```
ingest  →  extract  →  gather  →  rules  →  views
 bytes     ClaimGraph  EvidenceBundle  FindingsReport  what a person reads
```

Each arrow is a typed contract, which is what makes every stage testable alone:
`rules` never sees a PDF, `views` never sees a URL.

**The model translates; it never judges.** Three call sites. It converts unstructured
text to structured claims, structured findings to prose, and a skill name to one id
from M6's shared list (or none). It never produces a
number that enters a finding and never decides whether a claim is true.

Three things carry most of the weight:

**Span grounding.** Every claim carries verbatim text verified to exist in the
document. The model never emits character offsets — it returns the text and Python
recovers the offsets by search. Fuzzy matching is allowed above 0.92, *but every
digit sequence must be verified present regardless of the score*: a hallucinated
`rating of 1800` against a document saying `1495` scores 0.944, and numbers are
exactly where the decisive checks live.

**Every field is corroborated by its own span.** Grounding proves the text is real;
it does not prove the pairing is. Given a whole CV, `qwen3:1.7b` found one achievement
and stamped its values onto fourteen unrelated sentences — every verbatim genuine, so
grounding saw nothing wrong.

**Absence abstains.** A skill with no matching public artefact produces no finding.
Work code is private, coursework lives on institutional GitLab, and competitive
programming is not on GitHub at all.

---

## Layout

```
src/cvv/
  models/      the contract — claims, evidence, findings, API
  ingest       PDF · DOCX · OCR, normalisation, section detection
  spans        two-tier recovery with the numeral guard
  extract      8 narrow model passes, model-routed sections
  filters      the deterministic gate — four stages, each from an observed failure
  gather       Codeforces · LeetCode · CodeChef · GitHub · liveness, all cached
  codechef     the one scraped source — the public profile page
  providers    the model seam: Ollama, or Claude via the Claude Code wrapper
  skills       which shared skill each name means — rules, cache, then the model
  rules        28 checks, isolated, every one accounted for
  report       findings → five buckets
  narrative    findings → prose, one sentence per finding
  worksheet    what a person still has to do
  evaluate     the mutation harness
  api · cli · store
data/          roll schemes · technology releases · excluded exams · institutions
docs/plan.md   the phases and the full 41-check catalogue
CLAUDE.md      the guardrails, and why each one exists
```

[`docs/design.md`](docs/design.md) is the file to read next — also rendered as
[`docs/design.html`](docs/design.html) and [`docs/design.pdf`](docs/design.pdf)
(38 pages; regenerate with `uv run python scripts/render-pdf.py`) — every stage, every
design choice, and the failure that produced each one. `CLAUDE.md` holds the
guardrails in their working form.

---

## Development

```bash
uv run pytest                                   # 630 tests, no server needed
CVV_DATABASE_URL=postgresql:///cvv uv run pytest   # + the Postgres half
uv run pytest -m live                           # needs Ollama and the network
uv run ruff check . && uv run mypy
```

Logs go to stderr — human-readable on a terminal, JSON off one — and **never carry CV
content**. Events carry identifiers and counts; a scrubber drops the dangerous keys
whatever a caller passes.

---

## Status and limits

Every phase is complete for what is reachable. What remains is honest to state:

- **One document measured end to end since October.** The other two figures predate
  the CodeChef check and the fairness fixes.
- **Measured against three documents** in all, one of them synthetic. Each new one has found
  a real bug within minutes: the second, a section-routing failure; the third, a date
  format that silently disabled every employment check and a decisive finding fired on
  a thirteen-day notice period. More CVs is still the highest-value thing this project
  could be given.
- **A gold set of one.** `cvv gold` scores extraction against hand-labelled claims
  (precision, recall, F1 per kind, and each field); only the synthetic CV is labelled. Real
  CVs' gold files quote the person, so they belong under `out/`.
- **`qwen3:1.7b` is a small model.** Several failures documented in `CLAUDE.md` are
  its limits, not the design's. The Claude backend is the larger model; its runs are
  not seeded, so they are not reproducible run to run.
- **Personal data.** A stored report contains a real person's name, roll number,
  institutions and handles. Persistence is local by decision.
