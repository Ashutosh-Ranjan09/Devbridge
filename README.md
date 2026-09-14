# cvv — CV Verification Engine

Verifies developer CVs against the systems the candidate names: GitHub, Codeforces,
LeetCode, live deployments. Extracts typed claims with verbatim spans, gathers
evidence, runs deterministic checks, and emits findings with provenance.

**It produces no score and no verdict.** It reports evidence and says explicitly what
it could not check. A person decides what any of it means.

> DevBridge M5. Built against the contracts in `../discussion-ar/docs/`.

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
uv run cvv verify cv.pdf --json         # the full report
uv run cvv evaluate cv.pdf              # corrupt one fact and see what notices
uv run cvv rules                        # the live check catalogue
uv run cvv inspect cv.pdf               # read a document without calling a model
```

### Optional

```bash
uv sync --extra ocr                     # scanned PDFs (~100 MB of model weights)
export CVV_GITHUB_TOKEN=...             # 60 → 5000 API requests an hour
export CVV_DATABASE_URL=postgresql:///cvv
```

Configuration lives in `.env` (prefix `CVV_`); `.env.example` documents every setting
and what leaving it unset actually means. **`CVV_GITHUB_TOKEN` is the operator's
token, never the candidate's** — asking a candidate for a personal access token is a
phishing pattern, and nothing here needs one.

---

## What it checks

27 of a catalogue of 41. Six are human by design, one is excluded on fairness
grounds, and the rest are blocked on data nobody publishes.

| Group | Built | What it reads |
|---|---:|---|
| **D** document-intrinsic | 11/11 | the CV alone — dates, roll number, internal contradictions |
| **G** GitHub | 10/10 | REST + the GraphQL contributions calendar |
| **P** platforms | 5/6 | Codeforces and LeetCode public APIs |
| **W** deployments | 1/2 | an HTTP request, and the repo's declared homepage |
| **C** credentials | 1/5 | — issuer APIs do not exist |
| **H** human | 0/6 | — by design; `--worksheet` prepares them |

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

| | student CV | synthetic CV | professional CV |
|---|---|---|---|
| **detection** | 15/15 | 7/7 of applicable | 2/2 of applicable |
| **collateral** | 0 | 1 (correct) | 0 |

**Collateral** — rules firing on a mutation they had no business noticing — is the
number that matters. It started at 2, and both were real bugs: one would have
contradicted an honest CV decisively, and neither was visible to 294 passing tests.

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

Interactive docs at `/docs`. Binds to localhost — exposing it takes a deliberate
`--host`. An unset `CVV_API_KEY` generates one per run and prints it.

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

**The model translates; it never judges.** Two call sites. It converts unstructured
text to structured claims, and structured findings to prose. It never produces a
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
  filters      the deterministic gate — seven filters, each from an observed failure
  gather       Codeforces · LeetCode · GitHub · liveness, all cached
  rules        27 checks, isolated, every one accounted for
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
(35 pages; regenerate with `uv run python scripts/render-pdf.py`) — every stage, every
design choice, and the failure that produced each one. `CLAUDE.md` holds the
guardrails in their working form.

---

## Development

```bash
uv run pytest                                   # 466 tests, no server needed
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

- **Measured against three documents**, one of them synthetic. Each new one has found
  a real bug within minutes: the second, a section-routing failure; the third, a date
  format that silently disabled every employment check and a decisive finding fired on
  a thirteen-day notice period. More CVs is still the highest-value thing this project
  could be given.
- **No gold set.** Extraction *accuracy* is unmeasured; only rule detection is.
- **`qwen3:1.7b` is a small model.** Several failures documented in `CLAUDE.md` are
  its limits, not the design's, and a larger model is the intended upgrade path.
- **Personal data.** A stored report contains a real person's name, roll number,
  institutions and handles. Persistence is local by decision.
