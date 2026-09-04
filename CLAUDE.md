# CV Verification Engine

Verifies developer CVs against the systems the candidate names — GitHub, Codeforces,
LeetCode, live deployments, credential issuers. Extracts typed claims with verbatim
spans, gathers evidence, runs 41 deterministic checks, and emits calibrated findings
with provenance.

**It does not produce a score and it does not produce a verdict.** It reports evidence
and says explicitly what it could not check. A person decides what any of it means.

## Current state

**Nothing is built.** The repository was cleared on 2026-09-04 and restarted deliberately
simpler: one package, one process, no service mesh. The next concrete action is the
spike — one real CV end to end.

Read [`docs/plan.md`](docs/plan.md) for the phases and the full check catalogue.

## The invariant

**A CV from someone with no account, no repositories and no contest history must still
produce a complete, honest report.** The twelve document-intrinsic checks need no network
at all, so the document-only path is a real path, not a failure mode. Everything else
follows from this: abstention is a first-class result, and evidence gathering lives
inside this system rather than arriving from somewhere else.

## Guardrails — do not weaken these

They are cheap to implement and they are the difference between a report you would show
someone and one you would not.

1. **Span grounding.** Every claim carries verbatim text verified to exist in the source
   (NFKC-normalised). **The model never emits character offsets** — it returns the
   verbatim, Python recovers offsets by search. Ungroundable claims are dropped and
   `span_failures` increments. Build `recover_span` and its tests *before* the first model
   call.

   **Two tiers, and the second one needs a guard.** Exact match, or fuzzy above 0.92 —
   *but every digit sequence in the verbatim must be verified present in the document,
   regardless of the fuzzy score.* Measured against a real CV: a hallucinated
   `rating of 1800` where the document says `1495` scores **0.944** and passes a bare 0.92
   threshold. Changing one digit barely moves a similarity score, and numbers are exactly
   where the decisive checks live — ratings, ranks, problem counts, roll numbers, years.
   A fuzzy match without numeral containment lets through the precise corruption grounding
   exists to prevent, and it does so silently, because the claim looks properly grounded.

   ```python
   if not all(n in document for n in re.findall(r"\d+", verbatim)):
       reject()   # regardless of fuzzy score
   ```

   **Token-shaped fields are recovered, not trusted.** `handle`, repo owner,
   `credential_id`, roll number and URLs must each be a literal substring of the document;
   take the document's casing, not the model's. A model works in tokens and normalises —
   it will return `ar-009` for `AR009`, the API 404s, and you report that a real account
   does not exist. Prose fields (`org`, `title`, `degree`) are exempt: the model may
   legitimately normalise those.
2. **Only `DEFINITE` interval overlap raises a scoring discrepancy.** Most Indian CVs give
   year precision only; scoring `POSSIBLE` overlaps turns every clean CV into six
   contradictions. A single-year interval has an empty core span and can never be DEFINITE
   — that emptiness is the mechanism, not a defect.
3. **`gaps[]` is load-bearing.** A check that cannot run abstains *with a typed reason*,
   which flows into the report's "not evaluated" bucket. Silence would read as a pass.
4. **Absence abstains.** A skill claimed with no matching public artefact produces **no
   finding**. Work code is private, coursework lives on institutional GitLab, competitive
   programming does not live in GitHub at all. `claimed_languages - observed_languages =
   findings` is one line, passes a naive test suite, and flags every employed developer.
5. **Tier decides the bucket, mechanically.** `tier` is declared on the rule, never chosen
   per finding. An `attention` finding is unconstructable without its
   `innocent_explanation` — enforced by a model validator, so the reviewer always sees the
   benign reading alongside the signal.
6. **GitHub timeline checks use server-side timestamps only.** `git commit --date=` and
   `GIT_COMMITTER_DATE` are attacker-controlled. Use `repo.created_at`, `pushed_at`, and
   the GraphQL contributions calendar. Where no server-side value exists, leave the field
   `null` and open a gap.

And two that shape everything else:

- **The LLM translates, never judges.** It converts unstructured to structured, or
  structured to prose. It never produces a number that enters a finding and never decides
  whether a claim is true. Five call sites, listed in `docs/plan.md`.
- **No overall trust score. No verdicts.** `FindingsReport` has no `overall_score` field,
  deliberately. This is most tempting to add during demo prep — don't.

## Architecture

One package, one process. The tree reads in execution order:

```
ingest  →  extract  →  gather  →  rules  →  views
 bytes     ClaimGraph  EvidenceBundle  FindingsReport  what a person reads
```

Each arrow is a typed contract in `models/`. That is what makes every stage testable
alone: `rules/` never sees a PDF, `views/` never sees a URL.

Layout is MVC plus a service layer — `models/` `controllers/` `views/` for the first
three, and the four pipeline directories for the rest. Full annotated tree in
[`docs/plan.md`](docs/plan.md).

**Two structural rules:**

- **`rules/` imports only `models`, `intervals` and stdlib.** No `httpx`, no `gather`.
  Enforced by a test that walks the imports. If a rule needs data it arrives in the
  `EvidenceBundle` or the rule abstains.
- **`views/` takes only a `VerificationReport`.** `narrative.py` in particular: the
  faithfulness guarantee is that the function signature makes it impossible to introduce
  a fact nobody computed.

## Stack

```
core      python 3.12 · uv · pydantic v2 · pydantic-settings
llm       pydantic-ai → ollama (qwen3:1.7b) · nomic-embed-text
vectors   qdrant (local mode, no server)
web       fastapi · typer · httpx
data      postgres 16 · psycopg 3 + psycopg_pool — JSONB, plain SQL, no ORM
ingest    pymupdf · python-docx · rapidocr-onnxruntime [extra] · rapidfuzz
scrape    selectolax
test      pytest · pytest-asyncio · hypothesis · respx
eval      pandas · matplotlib
ops       structlog
quality   ruff · mypy --strict — installed, NOT gating
```

**Not used:** SQLAlchemy · Alembic · arq · Redis · MinIO · Celery · LangChain ·
OpenTelemetry · Docker Compose · gRPC.

Two hazards in that list:

- **`num_ctx` defaults to 4096 and truncates silently.** Set it explicitly on every model
  call, with a pre-send assertion that the prompt fits. Claims from the bottom of a CV
  vanish with no error otherwise. Verify pydantic-ai actually passes it through to Ollama
  before relying on it.
- **No `dateutil` for date parsing.** It is permissive by design and reads `2022-26` as
  June 2022 — a confidently wrong precision. The parser is table-driven and explicit, so
  an unrecognised format fails visibly.

`temperature: 0` and a fixed `seed` for reproducibility.

## Source documents

Design, read-only, outside this repository in `../discussion-ar/docs/`:

| File | Holds |
|---|---|
| `schemas/verification-report.schema.json` | **The authoritative data model** |
| `schemas/evidence-event.schema.json` | The M6 projection |
| `examples/report-full.json` · `report-degraded.json` | Reference payloads |
| `verification-check-catalogue.html` | All 41 checks, tiers, exclusions |
| `cv-to-skill-graph.html` | 22 claim shapes |
| `m5-integration-spec.html` | Endpoints and failure semantics — **§03 models are superseded by the schemas** |

Build `models/` from the **schemas**, not from the integration spec's code blocks. The
spec predates the decision to make GitHub and the competitive-programming platforms core
evidence, and building from it produces a system that structurally cannot run 18 of the
41 checks.

## Excluded by decision — do not build these

- **Entrance rank vs. published cutoff** — JEE cutoffs vary by reservation category;
  category-blind comparison systematically flags reserved-category candidates.
- **AI-generated CV detection** — using a model to write a CV is not fraud, and detection
  penalises non-native English speakers.
- **Identity verification, employment verification, degree and CGPA verification** — no
  accessible source. A degree from an institution can only be confirmed by that
  institution. These are named in the `out_of_scope` bucket, and the system must never
  imply otherwise.
- **Any overall trust score.**

Where a human must do the work, the system prepares it: the manual-check worksheet emits
what to verify, the parsed roll number, the registrar's contact, and the exact question
to ask.
