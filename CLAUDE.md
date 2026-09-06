# CV Verification Engine

Verifies developer CVs against the systems the candidate names — GitHub, Codeforces,
LeetCode, live deployments, credential issuers. Extracts typed claims with verbatim
spans, gathers evidence, runs 41 deterministic checks, and emits calibrated findings
with provenance.

**It does not produce a score and it does not produce a verdict.** It reports evidence
and says explicitly what it could not check. A person decides what any of it means.

## Current state

**27 of the 41 catalogued checks are built and the pipeline runs end to end** on
`docs/CV-SDE-AR.pdf` in ~20s on `qwen3:1.7b`. 374 tests, ~8,900 lines across 30
modules, ruff and `mypy --strict` clean.

One of the 41 — G12 — is excluded by decision rather than pending, so the buildable
target is 40. Six more (H1–H6) are human by design, and the system prepares their
worksheet instead. **The machine ceiling is 34, and 27 of it is built.**

**The system is measured, not asserted.** `cvv evaluate` corrupts one fact at a time
in a real document and asks whether the check responsible notices: **15/15 detection,
0 collateral**. Collateral — rules firing on a mutation they had no business noticing
— is the number that matters, and it started at 2. Both were real bugs, and one of
them would have contradicted an honest CV.

```
cvv.pipeline.verify(path)  ->  ClaimGraph, EvidenceBundle, FindingsReport

cvv verify cv.pdf [--brief] [--worksheet] [--json] [--offline] [--save DIR]
cvv evaluate cv.pdf [--baseline DIR] [--save-baseline DIR]
cvv serve [--host] [--port]        # the HTTP surface, docs at /docs
cvv rules | inspect | config
```

**The HTTP surface is §05 of the integration spec, in one process.** The spec draws
three services; this system collapsed them by an explicit decision, so the route
groups live together and call functions instead of each other. The two BOUNDARIES the
split existed to enforce survive, and they are the reason the split was drawn:
`/v1/narrate` accepts only a `FindingsReport` and `/v1/evaluate` only a `ClaimGraph`,
so neither can reach the document. That holds whether the call crosses a network or a
stack frame.

```
POST /v1/verifications              202 · Idempotency-Key honoured
GET  /v1/verifications/{id}         200 report · 202 while running · 404 unknown
GET  /v1/verifications/{id}/claims/{claim_id}/provenance
POST /v1/webhooks · GET /v1/usage · GET /healthz /readyz
POST /v1/extract /narrate /evaluate · GET /v1/rules
POST /v1/resolve /attest            501, with the reason
```

Four decisions worth not re-deriving:

- **No queue.** `arq` and Redis are in "not used"; `BackgroundTasks` runs the job in
  this process. Honest for one process, and the first thing to replace when it stops
  being one.
- **Two stores behind one Protocol**, chosen by `CVV_DATABASE_URL`. Memory needs
  nothing and loses everything on restart; Postgres survives one and can be shared
  between processes. A DSN that is set and unreachable RAISES rather than falling
  back — silently serving from memory when someone asked for a database is how a
  service comes back from a restart having lost everything while reporting itself
  healthy. `/healthz` names which store is in use, `cvv serve` warns when it is
  memory, and `cvv config` redacts the password out of the DSN.
- **`completed_degraded` has to mean something.** "Any gap" was the first definition
  and it was useless: CodeChef publishes no API, so every run has a gap and every
  report was degraded. A missing connector is a permanent property of the system and
  a NOT_FOUND account is a FINDING (G2). Degraded means something TRANSIENT stopped a
  check that could otherwise have run — re-running may return more.
- **A failure is still a `VerificationReport`**, with empty claims and findings rather
  than absent ones, so a client never needs two shapes. A verification that vanishes
  leaves the client polling and with nothing to tell the person whose CV it was.

**Persistence is JSONB, not an ORM.** The stored object is the `VerificationReport`
itself — a deep pydantic tree that already round-trips through JSON by contract — so
shredding it into mapped columns would create a second schema to keep in step with
the first. Columns hold only what has to be QUERIED: id, status, timestamps, and the
idempotency key under a partial UNIQUE index, because two concurrent retries of one
upload cannot be settled by a check-then-insert and the database is the only place
that race can be decided. Schema applied with `CREATE TABLE IF NOT EXISTS` at
construction; Alembic is in "not used", and one idempotent DDL statement is the
honest amount of machinery for two tables.

```bash
# a local server, peer auth over the unix socket — no password in the DSN
export CVV_DATABASE_URL="postgresql:///cvv"

# or throwaway, for a test run on a machine with no server
docker run -d --rm --name cvv-pg -e POSTGRES_PASSWORD=cvv -e POSTGRES_USER=cvv \
    -e POSTGRES_DB=cvv -p 55432:5432 postgres:16-alpine
export CVV_DATABASE_URL="postgresql://cvv:cvv@127.0.0.1:55432/cvv"
```

Both are exercised. `tests/test_store.py` runs its Postgres half only when the DSN is
set, so a default test run needs no server at all.

**Local, not hosted — decided, not pending.** A stored report holds a real person's
name, roll number, institutions and handles, so where the database lives is a
question about consent rather than about infrastructure. Neon or any hosted Postgres
would need NO code change — psycopg 3 speaks to it unchanged, and the schema applies
itself — which is exactly why the decision has to be made deliberately instead of
falling out of a connection string someone pasted. If it is ever revisited: real CVs
stay local, and anything hosted gets the synthetic fixture. Two values of one
environment variable, and the answer to "where is that person's CV stored" stays "on
my machine".

(For whoever does switch: a `-pooler` Neon endpoint is PgBouncer in transaction mode,
and psycopg 3 auto-prepares statements after five executions, which transaction
pooling does not support. It works for a few requests and then fails oddly.
`prepare_threshold=None`, or the direct endpoint.)

**One suite runs against both stores**, and that is not ceremony. The Protocol makes
mypy check they have the same SHAPE; only `tests/test_store.py` checks they have the
same BEHAVIOUR, and it caught two divergences on its first run. A duplicate
idempotency key made memory quietly rebind the key to a second verification while
Postgres raised a `UniqueViolation` that reached the client as a 500 — both now raise
`Duplicate` carrying the first id. And registering one webhook twice made memory fire
it twice per verification and Postgres fire it once.

Ingest reads **PDF, DOCX and scanned PDF** (`uv sync --extra ocr`). A PDF whose text
layer is thinner than 120 characters a page is a scan and goes to OCR automatically;
the report then carries a banner saying the text was inferred, because word
boundaries are where OCR fails and every reference-table match degrades with them.

Built: `models/` · `ingest` (PDF · DOCX · OCR) · `spans` · `extract` · `filters` ·
`dates` · `intervals` · `gather` (Codeforces · LeetCode · GitHub · liveness) ·
`github` · `leetcode` · `reference` · `rules` · `report` · `narrative` ·
`worksheet` · `evaluate` · `cli`.

| Group | Built | Missing |
|---|---|---|
| D · document-intrinsic | D2 D3 D4 D5 D6 D7 D8 D9 D10 D11 D12 | — |
| G · GitHub | G2 G3 G4 G5 G6 G7 G8 G9 G10 G11 — **all of them** | G12 is excluded by decision, below |
| P · platforms | P1 P2 P3 P4 P6 | P5 (CodeChef — no API, scraper only) |
| W · deployments | W1 | W2 (human — a reviewer opens the link) |
| C · credentials | C5 (narrative) | C1–C4 — blocked on DATA, not code |
| H · human | — | H1–H6, by design |

**None of the thirteen unbuilt checks is unbuilt because it is hard.** C1–C4 need
per-issuer credential APIs, AICTE/UGC registry data and institutional faculty
directories — acquisition problems, not engineering ones. P5 needs a scraper, which
is a source that breaks silently and answers wrongly. H1–H6 are human by design and
the system's job there is to prepare the worksheet, not to guess. G12 is excluded
outright.

**Reproducibility is measured, not assumed.** Same document and seed gives a
byte-identical claim set, including across a forced model reload. The one variable is
the GPU/CPU layer split, which Ollama picks from free VRAM at load time and which
moves the model's raw proposal count; pin `CVV_NUM_GPU` to remove it. The filters
absorbed that variance in every observed case — 18 proposals or 22, same findings.

**What is genuinely left** is G6 tier 2, which would read targeted repository files
to turn "the dependency is installed" into "the dependency is used for the thing
claimed" — the only remaining check improvement, and deliberately deferred: it opens
a prompt-injection surface whose contents the candidate chooses, for a gain the
manifest check already approximates. Everything else outstanding is data acquisition
(C1–C4), a source that does not exist (P5), or human by design (H1–H6).

Read [`docs/plan.md`](docs/plan.md) for the phases and the full check catalogue.

## The invariant

**A CV from someone with no account, no repositories and no contest history must still
produce a complete, honest report.** All eleven document-intrinsic checks are built and
need no network at all, so the document-only path is a real path rather than a failure
mode — `cvv verify --offline` is that path, and a test asserts every rule still appears
in the report with its reason. Everything else
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

9. **A check that is technically correct can still be unfair.** Nine rules, on their
   first version, would have put a false or misleading finding in front of a reviewer
   looking at an honest CV. None was a bug in the usual sense; each was a defensible
   reading of available data.

   | Rule | The tempting version | Why it is wrong |
   |---|---|---|
   | G5 | repository created after the claimed window | `created_at` bounds when the REPO existed, not when the WORK happened. The calendar showed 20 contributions in the claimed months |
   | G7 | fewer than N files means empty | an 11 KB program in two files is a program |
   | P2 | is the claimed rank anywhere in the history | true, useless, and it hid that the named contest was found three places out |
   | D9 | the roll number's department is not in the degree text | the CV named no department at all. Absence is not contradiction |
   | G6 | a claimed technology is missing from the repo | a CV names databases, protocols and services no language census or manifest can show. MongoDB is not a language and is not an npm package. Fire only when NOTHING matches |
   | G9 | claimed tenure exceeds the earliest evidence | the account is usually younger than the claim. Eight years of Python against a three-year-old GitHub reports when they joined GitHub |
   | G10 | no public commits during a claimed job | that is what a salaried job looks like from outside. Work code is private |
   | G11 | employer absent from public org memberships | org membership is private by default; most members never opt in |
   | D6 | stated total exceeds the dated roles | a CV need not list every role, and one page forces the choice |

   So: **state both numbers, not just the mismatch**; scale severity to the size of
   the gap; and where half a check can run and half cannot, say which — "could not
   check the roll number" and "checked the years, they line up, could not check the
   department" are different statements, and only one of them is true.

   Four of those nine survive as **corroboration-only** rules — G10, G11, P6 and the
   confirming half of G9. They can raise nothing and confirm something, which is not
   a weakened check but the correct shape when absence is the ordinary state of an
   honest candidate. `Corroborated` is the control signal, symmetric with `Abstain`,
   and what it says reaches the reader in the `verified` bucket. Where a table would
   make a rule fire, the entries are biased so it under-fires: every date in
   `data/tech-releases.json` is deliberately early, because a missed anachronism and
   a false accusation are not equally bad.

10. **A regex may recognise a token; it may never parse a CV.** A pattern encodes how
   ONE document happened to be phrased, and returns nothing — silently, on an honest
   CV — for every document phrased differently. Five of them were doing exactly that:

   | Was | Failed on |
   |---|---|
   | `round\s+#?(\d{2,4})` for the contest | AtCoder, LeetCode, ICPC, and "Round 2" |
   | `\d{2}[A-Z]{2}\d{5}` for the roll number | every institution but IIT Kharagpur — while `data/roll-schemes.json` held the shapes |
   | `could not verify\|self-declared` | any institution wording its footer differently |
   | `(platform)...handle:\s*(\w+)` | "Codeforces: ar009", a bare URL, a name in brackets |
   | `(\d+) years of experience` | "8 yrs", "since 2016", any other language |

   All five are model passes now. **Two regexes remain in the parsing path and both
   earn it:** `GITHUB_REPO`, because a URL's grammar is declared by the internet and
   not by a CV — and guardrail 1 is explicit that a model returns `ar-009` for
   `AR009`; and `PLATFORM_MENTION`, which is enforcement rather than parsing and is
   built FROM the contract's `Platform` enum so it cannot drift out of it. Roll
   numbers are still found by pattern, but the patterns come from the data file that
   interprets them, so a second institution is a data change and nothing else.

   The lever for a converted pass is the WINDOW, never a phrase. `header=`/`footer=`
   for a fact under no heading — positional windows carry no assumption about
   wording, which is the entire point.

   **And the section keyword lists were the same mistake one level up.**
   `sections=("ACHIEVEMENT", "AWARD")` encodes what one CV called its section. A
   second document headed that section "COMPETITIVE PROGRAMMING", matched nothing,
   fell back to the whole document, and lost two of three ratings and the only
   contest rank — silently, on a CV that had done nothing wrong. **The model routes
   the sections now**: it is shown the headings and says what each one holds, the
   answer is verified against headings the document actually has, and the keyword
   lists survive only as a fallback. Two things that cost a debugging round each:

   - **Route to one window per CONTIGUOUS run, never one window overall.** The real
     CV routes both `EDUCATION` and `COURSEWORK INFORMATION` to education —
     correctly — and they sit at opposite ends of the page. Spanning them turned a
     180-character window into a 4,252-character one. Choosing between them was the
     next wrong answer: longest-first picked COURSEWORK and lost every degree. The
     pass runs once per run and the claims merge.
   - **A category the model needs must exist even if no pass consumes it.** With no
     `coursework` category, coursework went to `education`, and the education pass
     turned "Computer Science" and "Mathematics" into degrees awarded by
     "University". D9 then picked one of those and abstained on a CV whose actual
     B.Tech was two claims away.

11. **A prompt is not an enforcement mechanism.** `qwen3:4b`, told explicitly to ignore
   JEE ranks, returned them anyway — and `qwen3:1.7b` returned them relabelled as
   `codeforces`, which no label-based filter can catch. Anything the design excludes is
   dropped by code reading the verbatim, which the model cannot alter.

And two that shape everything else:

- **The LLM translates, never judges.** It converts unstructured to structured, or
  structured to prose. It never produces a number that enters a finding and never decides
  whether a claim is true.

  The second call site proves the rule needs teeth. Asked for free prose over a report
  carrying four attention findings, `qwen3:1.7b` opened with *"the CV does not
  contradict any rules, as all claimed information is verified"* — a verdict, from a
  system whose first principle is that it produces none, and it passed a numeral check
  because it contained no numbers. So the model no longer writes a briefing: it writes
  **one sentence per finding**, Python assembles the frame, and three layers hold it —
  a signature that cannot reach the document, an omission check (every finding gets a
  sentence), and numeral containment **per finding** rather than per report. A number
  belonging to P1 in a sentence about G5 is the extraction failure arriving at the
  other end of the pipeline. Rejected prose falls back to a summary assembled by
  counting, and the CLI says why.
- **Measure the system, do not assert it.** `cvv evaluate` is not a test suite. A unit
  test proves a rule does what its author intended, using a fixture that author wrote
  to exercise it; it cannot prove the system catches a falsified CV. The harness
  corrupts one fact in a real document and reports two numbers. **Detection** is the
  quotable one and the easy one to inflate — "something fired" does not count, the
  rule responsible must be the one that noticed. **Collateral** is the honest one:
  rules firing on a mutation they had no business noticing. It found P3 comparing a
  LeetCode count against Codeforces, which would have contradicted an honest CV
  decisively, and it found D11 reporting a career gap between two mentions of one
  role. Neither was visible to 294 passing tests.
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
web       fastapi · uvicorn · typer · httpx
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
- **G12, contribution authenticity** — commit size distribution, to catch activity
  farming and bulk imports. Cost was never the objection: GraphQL `history { additions
  deletions }` returns 100 commits a query, roughly 40 for a whole account. It is
  excluded because it does not work and because it is shaped wrongly.

  It does not work in either direction. **Farming**: 400 commits with a median of one
  line is a cron job, and it is also `fix: typo in README` / `refactor: rename userId`
  / `test: add empty-input case` — the atomic-commit habit the industry teaches. No
  threshold separates them. **Bulk import**: one honest `npm install` writes
  `package-lock.json  +14,203 -0`, which *is* the signature; so does re-running one
  Jupyter cell, whose diff is base64 plot data.

  And it is shaped wrongly, which is the deciding argument. **Every other rule tests a
  claim** — P1 tests "peak rating 1495", G7 tests "this is a project", D7 tests "React
  in 2012". G12 tests no claim: the CV never says its author's commits are of
  representative size. There is nothing to contradict, only a habit to be suspicious
  of, and the innocent explanation cancels the finding on the page. It is also
  defeated by `random.randint(1, 400)`, so it selects for naive GitHub usage — which
  is students, deadline pushes, and people whose real work is private.
- **Identity verification, employment verification, degree and CGPA verification** — no
  accessible source. A degree from an institution can only be confirmed by that
  institution. These are named in the `out_of_scope` bucket, and the system must never
  imply otherwise.
- **Any overall trust score.**

Where a human must do the work, the system prepares it. `cvv verify --worksheet` emits
what to verify, the roll number already decoded, the exact question to ask and whom to
ask it of — and it invents nothing. A verification contact is printed only where the
operator supplied one in `data/institutions.json`, which ships EMPTY: a guessed
registrar address sends a candidate's details to a stranger, so an unlisted institution
gets its office named by role instead.

Two things the worksheet must never do, both learned from its first output:

- **A non-scoring finding never becomes a question for the candidate.** `scoring=False`
  marks findings that describe the extraction (D2), the document (D3, D4), a career's
  shape (D11, D12) or a naming habit (P6). The first version asked a candidate how two
  of nineteen proposed claims came to be dropped by our extractor, why their own CDC
  wrote a disclaimer, and to account for a gap in their dates.
- **A single-year education claim is a completion year, not an open range.** "Awarded
  from 2027 to ongoing" is a sentence the CV never said.
