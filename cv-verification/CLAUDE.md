# CV Verification Engine

Verifies developer CVs against the systems the candidate names — GitHub, Codeforces,
LeetCode, CodeChef, live deployments. Extracts typed claims with verbatim spans,
gathers evidence, runs deterministic checks from a catalogue of 43, and emits
calibrated findings with provenance.

**It does not produce a score and it does not produce a verdict.** It reports evidence
and says explicitly what it could not check. A person decides what any of it means.

## Current state

**31 of the 43 catalogued checks are built — every one in scope — and the pipeline
runs end to end** on `docs/CV-SDE-AR.pdf`: 30 registered rules plus the narrative
(C5), in ~20s on `qwen3:1.7b` or ~75s on Claude. 610 tests, ~11,400 lines across 33
modules, ruff and `mypy --strict` clean.

The other twelve are not pending. **C1–C4 are out of scope** for this project — a
decision, not a blocker. **W2 and H1–H6 are human by design**, and the system
prepares their worksheet instead. **G12 is excluded** (below).

**The system is measured, not asserted.** `cvv evaluate` corrupts one fact at a time
in a real document and asks whether the check responsible notices: **18/18 detection,
0 collateral**, including an inflated CodeChef rating, a CodeChef handle that does
not resolve, and the Codeforces lines left out by an extractor that obeyed the CV.
Collateral — rules firing on a mutation they had no business noticing — is the
number that matters, and it started at 2. Both were real bugs, and one of
them would have contradicted an honest CV.

```
cvv.pipeline.verify(path)  ->  ClaimGraph, EvidenceBundle, FindingsReport

cvv verify cv.pdf [--brief] [--worksheet] [--json] [--offline] [--save DIR] [--subject REF]
cvv evaluate cv.pdf [--baseline DIR] [--save-baseline DIR]
cvv serve [--host] [--port]        # the HTTP surface, docs at /docs
cvv rules | inspect | config | aliases [--promote NAME]
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
POST /v1/narrate /evaluate · GET /v1/rules
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
  and it was useless: before its scraper existed, CodeChef was a gap on every run, so
  every report was degraded. A missing connector is a permanent property of the system and
  a NOT_FOUND account is a FINDING (G2). Degraded means something TRANSIENT stopped a
  check that could otherwise have run — re-running may return more.
- **A failure is still a `VerificationReport`**, with empty claims and findings rather
  than absent ones, so a client never needs two shapes. A verification that vanishes
  leaves the client polling and with nothing to tell the person whose CV it was.

**`section_confidence` is a probability of CONTRADICTION, not a grade.** Noisy-OR
over the scoring discrepancies touching each section: `1 - Π(1 - confidence * weight)`.
Three things stop it becoming the score this system refuses to produce — non-scoring
findings never contribute, a section with no scoring finding is ABSENT rather than
zero (zero reads as "measured, found nothing" and gets averaged), and nothing is
combined across sections. The weight is the TIER, and it is not decoration:
`Discrepancy.confidence` says how sure we are of the OBSERVATION, so P2 recording
1109 against a claimed 1106 carries confidence 1.0, and raw confidences drove an
honest CV's achievements section to **1.0 on a three-place standings artefact**.
Weighted, it reads 0.4.

**M6 reads the report; this system does not project it.** `cvv verify --save DIR`
writes `verification-report.json` — the contract's `VerificationReport`, built by
`pipeline.verification_report()` and returned unchanged by `GET /v1/verifications/{id}`
— and M6 (`../skill-graph`) turns that into evidence events itself. Deciding what a
verified artefact is WORTH is a skill-graph judgement, so it lives there; an earlier
`events.py` here made the same projection and sent `surface:` skill ids M6
quarantined, every one. Three things the first real handoff taught:

- **The report carries every stage.** The capability signals are in the evidence
  bundle, not the findings, so a report without it is one M6 cannot project. The
  first version of this object had no bundle, subject, provenance or coverage, and
  nothing failed — because nothing parsed the whole thing. `test_contract.py` now
  builds one and requires it to validate.
- **Dates are the contract's, not the file's.** A PDF writes `D:20250704194743+05'30'`;
  the contract wants ISO 8601, and M6 refused the report because it dates every
  uncorroborated claim at the document's creation. jsonschema checks `format` only
  with an optional package, so a test checks it directly.
- **`subject_ref` is never derived from the CV.** Minting an identifier out of a name
  or a roll number makes someone linkable across verifications they never connected.
  The default is `subject:<document_id>`, which links only re-runs of the same file.

**We are ahead of the contract, and it is written down rather than silent.** 25 of the
27 definitions in `verification-report.schema.json` set `additionalProperties: false`,
so a field added here is a field that makes our output INVALID for a consumer
validating against the schema. Ten exist —`ExtractionMeta.filtered`,
`RepoEvidence.authored_files/authored_bytes/homepage`,
`GitHubEvidence.public_repos/public_repo_count`, `RuleOutcome.note`,
`Narrative.rejected_because`, `VerificationReport.failure`,
`VerificationReport.skill_resolution` — each load-bearing, and each
added unilaterally. The eighth was there all along and listed nowhere: `Narrative` was
not among the models the test compared. M6 tolerates all ten, because it does not
validate the report it reads. The integration spec predicted exactly this:
*"one person adds a field locally, the other never sees it, and integration breaks in
week 7."*

`tests/test_contract.py` now holds them as a NAMED list and fails on anything else, and
it round-trips the three reference payloads — the phase 0 guarantee, which was lost in
the clean-slate rebuild and restored only after roughly twenty model changes had gone
unchecked. Resolving the ten needs a contract version bump, which the spec says takes
both owners.

**Which skill a name means is resolved here, against one shared list.** M6 scores
skills by id from `../schemas/skills/` (`ontology.yaml`, `aliases.yaml`), and a name it
cannot place is set aside. `skills.resolve_skills` runs after the rules and writes
`skill_resolution` into the report — every name the claims, the language census and the
manifests carry, mapped to an id or to none, with who decided:

- **rules first**: the id itself, or an alias from the shared file;
- **then the cache** (`.cache/skill-resolution.json`, per ontology version), so a name is
  asked once and the next CV gets the same answer;
- **then the model**, for what is left: a CLOSED choice — one id from the list, or none.
  An answer off the list is none whatever it says, a skipped name is `unresolved`, and a
  model that is down leaves names unresolved for M6's own spelling rules.

That is resolution, not judgement: the contract names `llm_tiebreak` for it. The model
never sees the CV and cannot add a skill. `cvv aliases` lists its decisions and
`--promote NAME` makes one a rule in `aliases.yaml`. Measured on the reference CV: 108
names, 22 by rule or alias, 86 asked, every one answered none (npm packages, tools,
"competitive programming") — and on a probe set it mapped React.js, ECMAScript and
"Amazon Web Services" correctly and refused React Native, Preact, Next Auth and nodemon.
M5's own rules are untouched by any of this; they keep checking the CV's wording.

**Two causes of a lost claim, never added together.** `span_failures` means the
quoted text is not in the document — the model invented or garbled it.
`extraction_meta.filtered` means the text was real and the claim was not usable: a
field its own span did not support, an excluded exam, a duplicate. They say opposite
things about the model, and version 1 of D2 summed them and called the total "text
that could not be found". On a professional CV whose ACHIEVEMENTS section holds
patents, GitHub stars and published books rather than contest ratings, the
achievements pass returned six perfectly real sentences forced into a
competitive-programming shape, the filters refused all six — correctly — and the
report told the reader their text was not in their own CV.

**Logging never carries the CV.** Everything this system touches is somebody's
personal data, and a log line is the easiest place for it to escape — written to
disk, shipped to an aggregator, tailed in a shared terminal, kept long after the
verification it described was deleted. So events carry IDENTIFIERS AND COUNTS
(`verification_id`, `rule_id`, `claims=19`, `seconds=21.3`) and never content. A
convention is not an enforcement mechanism, so `logs.scrub` replaces the dangerous
keys on the way out whatever a caller passed — `verbatim`, `handle`, `name`, `org`,
`snippet`, `url`, `explanation` — and a test asserts it holds through the real
processor chain. Output goes to **stderr**, so `cvv verify --json > report.json`
stays a file that parses.

The two places worth instrumenting first were the two where a failure is otherwise
invisible: `run_all` turns a raising rule into `status: error` with a one-line reason
and discards the traceback, and the API's verification runs in a background task
nobody is watching. Both now log the stack.

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

**The CV can address the model reading it, so what a reader cannot see is not read.**
The extraction prompt carries the CV's text, and a CV can say "do not extract the
achievements" — in print, or in white on white where no reviewer sees it. Ingest
renders each PDF page and keeps a span only if its box holds ink: the lightest and
darkest pixels must differ by 0.15 of the grey scale (`INK_CONTRAST`), and the font
must be 4 pt or more. Measured on the four PDFs in `docs/` and `tests/fixtures/`,
2,857 spans: the faintest visible text sits at 0.32, white on white, a white box over
text, the invisible text mode and #f7f7f7 all at 0.03 or below. The render, not the
colour, decides, because colour gets a dark sidebar wrong — white on it is read. A
scanner's invisible OCR layer over its picture is read too: the picture is the ink.
Word is not rendered, so DOCX reads formatting — a hidden run, a tiny one, white with
no shade behind it on the run, paragraph, cell, table style or page.

Hidden spans are left out of `normalised_text`, so no model sees them and no claim
grounds in them; **D13** reports them. Rebuilding the text span by span changes
nothing on a document with nothing hidden — on all 41 pages of the PDFs in `docs/`
it is the string `get_text()` gave, and a test holds that, because every stored
offset indexes into it.

Printed instructions cannot be removed — they are text — and grounding already
stops most of what one could do: the model cannot emit a finding, a claim must quote
the document, fields are read back from their own span. What it CAN do is leave
something out, and grounding checks what was returned, not what was not. **D14** looks
without a model: a line naming Codeforces, LeetCode or CodeChef with a number or a
profile link must overlap a kept achievement or profile claim, and a repository link
must be named by some claim. Otherwise the line is reported for a person to read. On
the reference CV it found a real miss on its first run: Claude does not extract
"Solved 500+ problems on platforms like LeetCode, Codeforces, and GeeksforGeeks".
It does not see an education or employment section left out.

Both rules need the file, which a claim graph does not carry, so they read
`Context.reading` — internal, never serialised, because the contract's `document`
object is closed — and abstain on /v1/evaluate, which holds only a claim graph.

Built: `models/` · `ingest` (PDF · DOCX · OCR) · `spans` · `extract` · `filters` ·
`dates` · `intervals` · `ids` · `reference` · `cache` · `config` · `providers` · `skills` ·
`gather` (Codeforces · LeetCode · CodeChef · GitHub · liveness) · `github` ·
`leetcode` · `codechef` ·
`rules` · `report` · `narrative` · `worksheet` · `evaluate` · `logs` ·
`store` · `api` · `pipeline` · `cli`.

| Group | Built | Missing |
|---|---|---|
| D · document-intrinsic | D2 D3 D4 D5 D6 D7 D8 D9 D10 D11 D12 D13 D14 | — |
| G · GitHub | G2 G3 G4 G5 G6 G7 G8 G9 G10 G11 — **all of them** | G12 is excluded by decision, below |
| P · platforms | P1 P2 P3 P4 P5 P6 — **all of them** | — |
| W · deployments | W1 | W2 — human, by design: a reviewer opens the link |
| C · credentials | C5 (narrative) | C1–C4 — out of scope for this project |
| H · human | — | H1–H6, by design |

**Reproducibility is measured, not assumed, and the measurement has a limit.** Within
one model load it is exact: four consecutive extractions of the same CV were
byte-identical. Across loads it is not. Ollama picks the GPU/CPU layer split from
whatever VRAM is free AT LOAD TIME — the same machine reported 100% GPU and later 81%
in a single session — and that moves the model's raw proposal count.

The filters absorb that variance **usually, not always**. An earlier note here said
"in every observed case"; an audit then found a live extraction assertion failing once
in three runs, so the claim was wrong. Pin `CVV_NUM_GPU` for anything whose result you
intend to compare. A live run without it warns, so a single failure is not mistaken
for a regression.

**Two model backends, behind one seam.** `CVV_LLM_BACKEND` picks `ollama` (the
default, local) or `claude-code` — Claude through the local Claude Code wrapper at
`CVV_CLAUDE_CODE_URL`, with `CVV_CLAUDE_CODE_API_KEY` and `CVV_CLAUDE_CODE_MODEL`.
`default_provider()` is the only constructor, so nothing else knows which is running.
The wrapper has no `format` field, so the schema rides in the prompt and a code fence
is stripped from the reply; it has no seed either, so a Claude run is NOT
reproducible, and `model_id` (`claude-code:sonnet`) records which backend produced a
report. Measured once on the reference CV: Claude 73s, 19 claims, nothing dropped or
filtered; Ollama 98s, 20 claims, 2 filtered. Claude's project stacks were cleaner,
and it missed the "500+ problems" aggregate entirely, so P3 abstained.
`scripts/reproducibility.py` measures Ollama only.

**CodeChef is the one scraped source, and everything about P5 follows from that.**
There is no API, so `codechef.py` reads `/users/<handle>`, which robots.txt permits
(`/recent/user` is disallowed and never touched): the highest rating from the header,
the rated-contest history from the JSON the page embeds, the problems-solved total.
The evidence carries `source_quality: scrape`, and P5 is attention-only because of the
SOURCE, not the claim. A scraper fails by answering wrongly after a redesign, so a
field the page lacks is `None`, never 0, and an unrecognised page is a gap, never an
empty profile that reads as "solved nothing".

A missing handle is a finding, as G2 is for GitHub — but only when CodeChef redirects
the profile URL to its homepage, which is how it answers an unknown user (HTTP 200,
not 404). Any other redirect is a gap saying the site changed, so a URL redesign
cannot tell every candidate their account does not exist. CodeChef rarely changes its
URLs, and when it does the fix is the scraper, not the report.

**What is left is not a check.** G6 tier 2 would read targeted repository files to
turn "the dependency is installed" into "the dependency is used for the thing
claimed", and is deliberately deferred: it opens a prompt-injection surface whose
contents the candidate chooses, for a gain the manifest check already approximates.
Beyond that the gap is measurement — every number above comes from one real CV, there
is no gold set, and extraction accuracy is unmeasured.

Read [`docs/plan.md`](docs/plan.md) for the phases and the full check catalogue.

## The invariant

**A CV from someone with no account, no repositories and no contest history must still
produce a complete, honest report.** All thirteen document-intrinsic checks are built and
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
   present = set(re.findall(r"\d+", document))
   if not all(n in present for n in re.findall(r"\d+", verbatim)):
       reject()   # regardless of fuzzy score — and as whole runs: 149 is not in 1495
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

9. **A check that is technically correct can still be unfair.** Sixteen rule
   versions would have put a false or misleading finding in front of a reviewer
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
   | D5 | any DEFINITE overlap between two full-time roles | a thirteen-day overlap is a notice period. You start the new job while notice at the old one runs, or the last day is on the books after the next has begun |
   | G4 | investigate the first owner the repository URLs name | a CV linking its own repositories and `apache/kafka` had Apache checked as the candidate. The account is the handle the CV states, else the owner of most linked repos; a repo under another owner is a contribution claim, asked about by commits |
   | D9 | decode any token shaped like a roll number | every institution's number got IIT Kharagpur's department table. A scheme applies only where the CV names its institution as a whole word — "vit" is in "activities" |
   | D10 | two non-overlapping mentions of one role disagree | that is a return internship — two stints. It fires when ONE stint is given two irreconcilable accounts |
   | W1 | a URL that does not answer 200 is dead | a timeout, a login wall or bot protection is not a 404. Only 404 and 410 are decisive; no response at all is a transient gap |
   | P2 | the claimed number appears in the span | as a substring, `10` is in "1106". Numbers are matched whole, here and in the grounding guard |
   | G6 | no stack match is a contradiction | with no manifest read, a language census cannot see a library or a database. G6 reads all five manifest formats wherever they sit, and abstains when it read none |

   So: **state both numbers, not just the mismatch**; scale severity to the size of
   the gap; and where half a check can run and half cannot, say which — "could not
   check the roll number" and "checked the years, they line up, could not check the
   department" are different statements, and only one of them is true.

   Four of those survive as **corroboration-only** rules — G10, G11, P6 and the
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
12. **The candidate's words never reach a model by way of a finding.** The narrative's
   model reads each finding's explanation and params, so a rule that quoted a hidden
   instruction would deliver it to the next model. D13 and D14 quote the CV under
   `params[CANDIDATE_TEXT]`, which `narrative.facts` drops and the CLI prints with
   `repr` (a control sequence in a CV prints as text). Older rules — D3 is one — quote
   short verbatims in their explanations; a new rule quotes under the key.

And two that shape everything else:

- **The LLM translates, never judges.** It converts unstructured to structured,
  structured to prose, or a name to one id from a closed list. It never produces a number
  that enters a finding and never decides whether a claim is true.

  The narrative call site proves the rule needs teeth. Asked for free prose over a report
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
alone: `rules.py` never sees a PDF, `narrative.py` never sees a URL.

The package is flat — one module per stage, plus `models/` for the contract. The
annotated tree is in [`docs/design.md`](docs/design.md) §2.

**Two structural rules:**

- **`rules.py` imports only PURE modules** — `models`, `intervals`, `ids`, `filters`,
  `reference`, `logs` and stdlib. No `httpx`, no `gather`. If a rule needs data it
  arrives in the `EvidenceBundle` or the rule abstains. `tests/test_structure.py`
  walks the imports and holds the pure list, with a reason beside each entry; before
  that test existed this paragraph claimed an enforcement that was not there, and the
  rule it described had already drifted.
- **`narrative.py` takes only a `FindingsReport`.** The faithfulness guarantee is that
  the function signature makes it impossible to introduce a fact nobody computed, and
  `tests/test_structure.py` asserts it imports nothing that reaches the document.

## Stack

```
core      python 3.12 · uv · pydantic v2 · pydantic-settings
llm       httpx → ollama (qwen3:1.7b) · or the local Claude Code wrapper
web       fastapi · uvicorn · typer · httpx
data      postgres 16 · psycopg 3 + psycopg_pool — JSONB, plain SQL, no ORM
ingest    pymupdf · python-docx · rapidocr-onnxruntime [extra] · rapidfuzz
scrape    selectolax (lexbor backend) — the CodeChef profile page
test      pytest · pytest-asyncio · hypothesis · respx
ops       structlog — stderr, JSON off a terminal
quality   ruff · mypy --strict — installed, NOT gating
```

**Planned, not installed:** qdrant · nomic-embed-text · pandas · matplotlib.

**Not used:** pydantic-ai · SQLAlchemy · Alembic · arq · Redis · MinIO · Celery · LangChain ·
OpenTelemetry · Docker Compose · gRPC.

Two hazards in that list:

- **`num_ctx` defaults to 4096 and truncates silently.** Set it explicitly on every model
  call, with a pre-send assertion that the prompt fits. Claims from the bottom of a CV
  vanish with no error otherwise. `OllamaProvider` does both itself, over Ollama's HTTP
  API — there is no framework in between to lose the parameter.
- **No `dateutil` for date parsing.** It is permissive by design and reads `2022-26` as
  June 2022 — a confidently wrong precision. The parser is table-driven and explicit, so
  an unrecognised format fails visibly.

`temperature: 0` and a fixed `seed` for reproducibility — on Ollama. The Claude backend
has neither, and says so in `model_id`.

## Source documents

Design, read-only, at the repository root: the contract in `../schemas/`, the design pages in
`../docs/`. M6 reads the same copy.

| File | Holds |
|---|---|
| `../schemas/verification-report.schema.json` | **The authoritative data model** |
| `../schemas/evidence-event.schema.json` | What M6 makes of a report — M6's input, not ours |
| `../schemas/examples/report-full.json` · `report-degraded.json` | Reference payloads |
| `../docs/verification-check-catalogue.html` | All 43 checks, tiers, exclusions |
| `../docs/cv-to-skill-graph.html` | 22 claim shapes |
| `../docs/m5-integration-spec.html` | Endpoints and failure semantics — **§03 models are superseded by the schemas** |

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
