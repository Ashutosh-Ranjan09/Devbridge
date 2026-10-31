# DevBridge — Assessment

From a job description to a coding task that is **unique to each candidate and exactly
as hard as everyone else's**, run in a sandbox, scored by hidden tests only, and fed
back into the skill graph (M6) as evidence.

**No overall score of a person, no verdict, no filtering.** A job's assessment is scored
like an online test: each task on its own, and a total over that job's tasks (100 points
each). A result names every test, whether it
passed, and why not. A person decides what it means.

## State

Built end to end: JD intake (extract · edit · confirm · export), pattern library with
validation, variant generation, Docker sandbox, scoring, sessions, the M6 feed and
calibration, an HTTP API (`assess serve`) — and in M6, the shortlist and the
`assessment_result` event kind.
130 tests, plus 12 that need Docker (`-m docker`), 1 that needs the model (`-m live`)
and 1 that takes over a minute (`-m slow`). ruff and `mypy --strict` clean. Two
patterns: `rate_limiter` (skill `rate_limiting`) and `top_k_frequent`, a DSA problem
(skill `algorithms`).
`docs/plan.md` is the design and the build record.

```
assess jd new jd.txt [--no-model]            propose skills, each quoted from the JD
assess jd edit JOB --must ID[:BAR] --nice ID --drop ID --task PATTERN
assess jd confirm JOB --by NAME               locks it; a confirmed job is never edited
assess jd export JOB --out requirements.json  → M6: python -m m6_query shortlist --requirements …
assess start --job JOB --candidate REF        the job's chosen tasks
assess start PATTERN --candidate REF          one task from a named pattern
assess submit SESSION solution.py             sandbox → report
assess report SESSION [--json] · events SESSION --out batch.json → M6 ingest
assess patterns · validate PATTERN · calibrate PATTERN · sandbox build
assess serve [--port 8070]                    the same commands over HTTP, for web/
```

### HTTP (`assess serve`, `src/assess/api.py`)

The CLI's commands as endpoints: parse, call, return — no rule of its own. Bearer key
from `ASSESS_API_KEY` (generated and printed when unset); `/healthz` is open. Errors are
flat `{"error", "detail"}`, like M6's: 404 unknown id, 409 the module's own refusal
(the message says why), 422 a malformed body, 503 the sandbox could not run.

| | |
|---|---|
| `GET /healthz` | Docker present, sandbox image built |
| `GET /v1/patterns` | id, skill, level, variants, twists |
| `POST /v1/jobs` `{text, model}` · `GET /v1/jobs[/{id}]` | propose skills from a JD (synchronous, up to the model's timeout) |
| `PATCH /v1/jobs/{id}` `{must:{id:bar}, nice, drop, tasks?}` · `POST …/confirm` `{by}` | a person's edits, then the lock; bars checked 0–1; `tasks` is the patterns every applicant gets, each testing a must-have |
| `GET /v1/jobs/{id}/tasks` | each must-have with the patterns that test it, the chosen ones ticked, and those no pattern tests |
| `GET /v1/jobs/{id}/results` | `tasks`: each task ranked on its own, by hidden tests passed then time, equal places shared (`scoring.standings`), the rest under `pending`; `assessment`: each candidate's total, 100 points a task summed over the job's tasks, then less time (`scoring.totals`), ranked once every task is final or expired, the rest `in_progress` |
| `GET /v1/jobs/{id}/requirements` | the body for M6's `POST /shortlist` |
| `POST /v1/sessions` `{candidate_ref, job_id \| pattern_id, start_by?}` | issue tasks; asking again returns the same ones. A job's tasks are `issued` with no clock, to be started by `start_by` (default 7 days, at most 60); practice starts at once |
| `POST /v1/sessions/{id}/begin` | the candidate presses Start: the time limit runs from now and the task is shown; again changes nothing; after `start_by`, 409 |
| `GET /v1/sessions/{id}` | the task — never the hidden tests, seed or parameters, and before Start not its story, requirements or starter. Past its start-by date or deadline (plus grace) it reads, and is stored, `expired` |
| `POST /v1/sessions/{id}/run` `{code}` | the visible examples in the sandbox, each with its detail; stored nowhere, no attempt used, unlimited while open |
| `POST /v1/sessions/{id}/submit` `{code}` | the hidden tests: one attempt of `max_attempts` (3); returns the candidate view, `final` and `attempts_left`. Code that does not parse: 422 `syntax_error`, no attempt used |
| `POST /v1/sessions/{id}/finish` | the candidate is done: the last attempt counts now |
| `GET /v1/sessions/{id}/attempts[?view=full]` | every attempt; `counted` (the last) once final |
| `GET /v1/sessions/{id}/result[?view=full]` | the counted result, once final (404 before): `candidate` by default, test names and passed, no failure detail (it quotes the hidden tests); `full` for the person reading results |
| `GET /v1/sessions/{id}/events` | the batch for M6's `POST /evidence/batch` |

Who may ask for `view=full` is the web layer's decision; what each view holds is this
module's.

Run from anywhere: settings come from `assessment/.env` (prefix `ASSESS_`), the same
Claude Code wrapper cvv uses. Sessions, jobs and results live in `.data/assess.db`,
which git ignores — they name candidates. One `Store` per HTTP request, opened with
`check_same_thread=False`: FastAPI may run a dependency's setup and teardown on different
threads. Never share one Store between requests.

## Guardrails — do not weaken these

1. **The model chooses; it never invents anything that is scored.** Skills come from
   `../schemas/skills/`, parameters from the pattern's allowed lists, hidden tests from
   code. An off-list choice is replaced by the seeded one; a story whose numbers are not
   the variant's own is discarded for the template. Free-form generated constraints
   made the original design's three candidates' tasks unequal, and a generated test
   would fail a candidate for the test's own mistake.
2. **A pattern is used only after its tests are proven right in every combination.**
   The reference must pass every case; every mutant must fail at least one case in every
   combination it applies to. Cached by a hash of the pattern's files, so any edit
   forces it again. `assess validate` shows the evidence: 648 cases, 8 mutants, 0
   escapes for rate_limiter; 216 cases, 11 mutants, 0 escapes for top_k_frequent.
   Validation gives each test the sandbox's own 2 s (`sandbox.PER_TEST_SECONDS`), on
   the full CPU, so a reference too slow for the sandbox cannot pass validation.
3. **Equal difficulty is enforced, not hoped for.** Twists must share one rating or the
   pattern does not load. Calibration measures whether they really are equal; a flagged
   twist is moved out by a person, which bumps the version. Versions are never mixed.
4. **A run that could not happen is not a score.** `sandbox_unavailable` leaves the
   session open, uses no attempt and emits no evidence. Code that does not parse is
   refused before the sandbox (`compile()` only, nothing runs) and uses no attempt: a
   cut-off paste is an accident, not an answer. Everything else the candidate caused is
   scored, `import_error`, `timeout` and `resource_limit` as zero, with the reason.
5. **Candidate code runs only in Docker** — no network, read-only mount, memory, CPU
   and process limits, non-root, 2 s per test, 30 s per run. Trusted code (reference,
   mutants) is validated locally. Never route candidate code through `validation.py`.
6. **JD skills are grounded.** A proposed skill whose quote is not in the JD is dropped
   and counted; an inferred one ("protect our login endpoint" → rate_limiting) is kept
   and marked for review. Nothing reaches a shortlist that a person has not confirmed.
7. **Unknown is said, never dropped.** A JD skill not on the list, a must-have with no
   pattern, a skill M6 does not know: each is reported where a reader will see it.
8. **The shortlist filters on must-haves and never ranks.** Ordering by several skills
   needs a weighted sum. M6 does publish one, by the project owner's decision — a job
   match per applicant, beside the columns — but it orders and filters nobody.
9. **Results are immutable.** Triggers refuse UPDATE and DELETE on results, submissions
   and attempts; the code that was scored is stored beside each attempt. Up to three
   attempts; the LAST counts, written to `results` once the session is final (the last
   attempt, one passing every test, Finish, or the deadline). Events and calibration read
   only that, so M6 never hears of an attempt the candidate could still replace.
10. **This module emits facts; M6 prices them.** The event carries level, tests passed
    and total; `observed_value.assessment_result` in M6's parameters turns that into an
    ability estimate. How far to TRUST a result is `contracts/evidence.yaml`.

## Known limits, stated

- **A job's results are ranked: per task, and as an assessment total.** Per task: hidden
  tests passed, then time from Start to the counted submission. Total: each task worth
  100 points (its share of tests passed, so 6 tests and 8 tests weigh the same), summed
  over the job's chosen tasks, then less total time; a task that expired with nothing
  submitted scores 0, and nobody is ranked until every task is final or expired.
  Attempts never order anyone. Coarse: with 6–8 tests many share a count and time
  decides, which rewards speed. A rank says nothing about why a test failed; the full
  result does. The total is this test's score only: never added to skills or other jobs,
  never sent to M6.

- **Tasks are chosen per job, not per candidate.** The recruiter ticks which patterns
  every applicant gets while the job is a draft (default: each must-have's first); the
  choice locks with the job, so two applicants to one job always face the same tasks. A
  must-have new in an edit starts with its first pattern ticked. An unbarred must-have
  no chosen task tests is filtered on any direct evidence (bar 0.0) at confirmation, and
  exported `assessable: false`. A job from before the choice (`tasks: null`) issues each
  must-have's first pattern.

- **The clock starts at Start, not at Send.** A job's task waits, text withheld, until the
  candidate begins it; the recruiter chooses the start-by date. The time limit is the
  pattern's and the same for everyone (guardrail 3); the recruiter never changes it.
  `assess start --job` begins at once: an operator there means to take the task now.

- **Help is not prevented.** Unique variants stop copying from another candidate; the
  time limit narrows outside help; nothing stops an AI assistant. A follow-up step
  ("now change the rule to…") is the next answer, not built.
- **In-process tests.** Candidate code is imported by the pytest process that writes
  the result file. The path is random and the case count is checked; a deliberately
  malicious solution could still try to forge it. The stored code is the audit trail.
- **Two patterns.** `api_security`, `python`, `postgresql` and every other must-have
  are reported "not assessable" until a pattern exists. The second pattern, a DSA
  problem, needed one change to module code (test ids built from the pattern's own
  parameters), so the format does generalise; both are Python.
- **Calibration thresholds are placeholders** (20 points, 15 attempts) until there is
  real data.

## Adding a pattern

`patterns/<id>/`: `pattern.yaml` (skill must be on the shared list; twists one rating),
`starter.py`, `requirements.md` and `story.md` with `{param}` and `{param_label}`
placeholders, `tests_hidden.py` reading `params.json` (test names must equal the
declared groups), `tests_visible.py` — the Run button's examples, read straight off the
requirements and leaving every edge to the hidden tests (names in `tests.visible`; the
reference must pass them too) — `reference.py` implementing every twist at once, and `mutants/` —
`twist_<twist>__*.py` for a twist-only bug. Then `assess validate <id>` until it says
valid.

- **Test ids** inside `[...]` must be the parameter values in `pattern.yaml`'s order,
  then the twist, joined by `-` (`product_id-3-with_counts`). Validation matches
  failures to combinations by that id; a mismatch shows every mutant escaping.
- **Twists must be compatible**, because one reference implements them all: an extra
  header, an extra function. Rules that contradict (two different tie orders) cannot
  be twists; fix one in the core instead.
- **A performance test** works through the 2 s per-test limit: size the input so the
  reference passes in the sandbox (`-m docker`) and the slow mutant times out. Each
  timed-out case costs 2 s of validation, so put that pattern's full run under
  `@pytest.mark.slow` and validate one combination per twist by default.
