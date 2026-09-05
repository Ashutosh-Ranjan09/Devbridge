# CV Verification Engine

Verifies developer CVs against the systems the candidate names — GitHub, Codeforces,
LeetCode, live deployments, credential issuers. Extracts typed claims with verbatim
spans, gathers evidence, runs 41 deterministic checks, and emits calibrated findings
with provenance.

**It does not produce a score and it does not produce a verdict.** It reports evidence
and says explicitly what it could not check. A person decides what any of it means.

## Current state

**Working end to end.** `docs/CV-SDE-AR.pdf` runs in ~15s on `qwen3:1.7b`: 17 claims
extracted, live evidence gathered from Codeforces and GitHub, **10 of the 41 checks**
evaluated, five buckets printed. 131 tests. ~5,600 lines.

```
cvv.pipeline.verify(path)  ->  ClaimGraph, EvidenceBundle, FindingsReport
```

| Built | |
|---|---|
| `models/` `ids` `intervals` | the contract, stable ids, three-valued date algebra |
| `ingest` | PDF, NFKC + index map, section detection, line lookup |
| `spans` | two-tier recovery, numeral guard, span-scoped token recovery |
| `dates` | table-driven parser; `2022-26`, seasons, two-digit years |
| `extract` | regex pre-pass + 4 section-scoped model passes + grounding |
| `filters` | the deterministic gate — seven corroboration filters |
| `gather` `github` `cache` | Codeforces, liveness, GitHub REST + GraphQL calendar |
| `rules` | P1 P2 P3 · W1 · G2 G4 G5 G7 G8 · D9 + registry + isolation runner |
| `report` | tier→bucket, coverage, five buckets |
| `reference` `data/` | roll-number schemes, programme durations |

**Not built:** G6 (needs project technologies from the extractor), 31 further checks,
the narrative renderer, storage, the API surface, and the evaluation harness.
`scripts_spike.py` is still a scratch entry point rather than `cvv/cli.py`.

**Reproducibility is measured, not assumed.** Same document and seed gives a
byte-identical claim set, including across a forced model reload. The one variable is
the GPU/CPU layer split, which Ollama picks from free VRAM at load time and which
moves the model's raw proposal count; pin `CVV_NUM_GPU` to remove it. The filters
absorbed that variance in every observed case — 18 proposals or 22, same findings.

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
7. **Every field must be corroborated by the claim's OWN span** — not merely be present
   somewhere in the document. This one is not in the original design; it comes from
   watching a real model fail.

   Grounding proves the *text* is real. It does not prove the *pairing* is. Given the
   whole CV, `qwen3:1.7b` found one achievement — Codeforces 1495 Specialist — and then
   stamped those same field values onto fourteen unrelated sentences, including the CV's
   name header. Every verbatim was genuine and 1495 was a genuine rating, so grounding
   saw nothing wrong. It also labelled a CodeChef rating `codeforces`, which would have
   compared 1733 against Codeforces' 1495 and fired a decisive contradiction against an
   honest candidate.

   So each field is read back from the span that cites it:

   | Field | Rule |
   |---|---|
   | `value` | the number must appear in this claim's verbatim |
   | `platform` | whichever platform the verbatim names; none named → unattributable |
   | `proficiency` | the band the sentence uses, or `None`. Never invented |
   | `handle`, owner, ids | recovered from the span, with the document's casing |
   | two or more platforms named | flag `aggregate_across_sources`; the rule abstains |

   A field the span does not support is dropped — the claim usually survives without it.

8. **Extraction runs narrow passes over sections, never one wide call.** Measured on a
   real CV: one call with every field optional returned 18 claims carrying `kind` and
   `verbatim` and nothing else. Four calls with `required` in the JSON schema returned
   every value correctly. `required` is the lever — an optional field is one a small
   model will skip.

   Section scoping is the largest single quality lever. Whole document: 1 of 4
   achievements correct. The 817-character achievements section: 4 of 4, and four times
   faster. The window is a *boundary*, not a hint — a claim whose text is not in its
   pass's own section does not belong to that pass, and must not be rescued by a
   document-wide search.

   Ask the right question, too. The skills pass returned the CV's own category
   headings as skills — `programming languages`, `utilities` — and the plan was an
   ontology lookup to filter them. Not needed: asking *"what category is each item"*
   instead of *"list the skills"* made both models exclude the headings by themselves,
   because a heading has no plausible category. Junk output is often a task-framing
   problem before it is a capability one.

9. **A check that is technically correct can still be unfair.** Four rules, on their
   first version, would have put a false or misleading finding in front of a reviewer
   looking at an honest CV. None was a bug in the usual sense; each was a defensible
   reading of available data.

   | Rule | The tempting version | Why it is wrong |
   |---|---|---|
   | G5 | repository created after the claimed window | `created_at` bounds when the REPO existed, not when the WORK happened. The calendar showed 20 contributions in the claimed months |
   | G7 | fewer than N files means empty | an 11 KB program in two files is a program |
   | P2 | is the claimed rank anywhere in the history | true, useless, and it hid that the named contest was found three places out |
   | D9 | the roll number's department is not in the degree text | the CV named no department at all. Absence is not contradiction |

   So: **state both numbers, not just the mismatch**; scale severity to the size of
   the gap; and where half a check can run and half cannot, say which — "could not
   check the roll number" and "checked the years, they line up, could not check the
   department" are different statements, and only one of them is true.

10. **A prompt is not an enforcement mechanism.** `qwen3:4b`, told explicitly to ignore
   JEE ranks, returned them anyway — and `qwen3:1.7b` returned them relabelled as
   `codeforces`, which no label-based filter can catch. Anything the design excludes is
   dropped by code reading the verbatim, which the model cannot alter.

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
