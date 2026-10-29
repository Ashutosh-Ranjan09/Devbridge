# assess — DevBridge assessment

A recruiter gives a job description. The module proposes the skills it asks for, a
person confirms them, the skill graph shortlists candidates who clear every must-have,
and each chosen candidate gets a coding task that is unique to them and exactly as hard
as everyone else's. Their code runs in a sandbox, is scored by hidden tests, and the
result goes back into the skill graph.

No overall score, no verdict: a result says which tests passed and why the others did
not.

## Quickstart

Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
uv sync
uv run assess sandbox build                  # the image candidate code runs in
uv run assess validate rate_limiter          # prove each pattern's tests first
uv run assess validate top_k_frequent        # the DSA one: about 80 s, once
```

### A job, end to end

```bash
uv run assess jd new jd.txt                  # proposes skills, each quoted from the JD
uv run assess jd edit JOB --must rate_limiting:0.3 --must python:0.35
uv run assess jd confirm JOB --by "recruiter:me"
uv run assess jd export JOB --out requirements.json

# who qualifies — in the skill graph
cd ../skill-graph
PYTHONPATH=packages python3 -m m6_query shortlist --db evidence.db --requirements ../assessment/requirements.json

# a task for one of them
cd ../assessment
uv run assess start --job JOB --candidate subject:doc_…     # writes task-<session>/TASK.md + solution.py
uv run assess submit SESSION task-SESSION/solution.py      # sandbox → report
uv run assess events SESSION --out batch.json               # the result as evidence
cd ../skill-graph && PYTHONPATH=packages python3 -m m6_ingestor ingest ../assessment/batch.json --db evidence.db
```

### Over HTTP

```bash
uv run assess serve                          # :8070; prints a key unless ASSESS_API_KEY is set
```

The same commands as endpoints, for the web layer — see the table in
[`CLAUDE.md`](CLAUDE.md#http-assess-serve-srcassessapipy).

## How a task stays fair

| | Done by |
|---|---|
| The pattern, its allowed values, its reference solution and mutants | a person, once |
| Proving the tests right in every combination | code: reference passes, every mutant fails |
| Choosing a candidate's values | the model, from the allowed lists only — or a seed |
| The scenario story | the model, with no numbers of its own |
| The requirements text and the hidden tests | code, from the chosen values |
| Running and scoring | the sandbox; tests passed, nothing else |

## Tests

```bash
uv run pytest                 # 93, no Docker, no model
uv run pytest -m docker       # 10, real sandbox runs
uv run pytest -m slow         # 1, the DSA pattern in every combination
uv run pytest -m live         # 1, the real model
uv run ruff check . && uv run mypy
```

Read [`CLAUDE.md`](CLAUDE.md) for the guardrails and [`docs/plan.md`](docs/plan.md) for
the design.
