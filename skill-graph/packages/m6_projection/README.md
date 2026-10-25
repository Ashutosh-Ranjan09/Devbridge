# m6_projection — event projection

**Status: complete (v1.0.0).** M6 submodule 6.0, the seam between M5 and the skill graph.

Turns one M5 `VerificationReport` into an `EvidenceEventBatch`. It is the only
place that decides *what capability signal a verified artefact carries*. It does
not decide whether a claim is true — M5 already did — and it does not compute a
score, which is 6.3's job.

```python
from m6_projection import project
batch = project(json.load(open("report-full.json")), module_version="0.4.1")
json.dump(batch.to_dict(), out)
```

```
python3 -m m6_projection docs/docs/examples/report-full.json --out batch.json
make test        # 102 tests, no pytest required
```

Stdlib only, except `yaml` to read the contract and `jsonschema` in the tests.

## Layout

| file | holds |
|---|---|
| `params.py` | Loads `contracts/projection-rules.yaml`. **No threshold is hard-coded anywhere in this package** — the sweep edits YAML, never Python. |
| `rules.py` | Pure decisions: substance bands, relevance, reliability factors, event ids. No I/O, no clock, no report structure. |
| `projector.py` | Walks the report, builds the batch, enforces the six invariants. |
| `models.py` | Dataclasses mirroring the schema. Generated from it with pydantic v2 in the real repo; field names match so the swap is mechanical. |

## Three properties worth preserving

**Deterministic.** `event_id` is `sha256(verification_id, kind, discriminator)[:12]`,
so replaying a batch is a no-op. O4's fold needs a total order and idempotent
ingestion needs reproducible ids; a random id breaks both.

**Consent-gated first.** No `consent_ref` means zero events, checked before any
evidence is read. Skill-graph inclusion is a different purpose from verification.
Configurable at `thresholds.consent.require_consent_ref`; defaults to strict.

**Silent on nothing.** Every drop lands in `not_emitted[]` with one of the five
schema reasons. A skill that resolves to nothing lands in `quarantined` rather
than disappearing.

## What it does not do

The schema has **no `observed` field** (`additionalProperties: false`), so the
observation value is not the projection's to set. It emits raw facts in
`payload` — the substance band, the commit count, the confirmed problem count —
and `m6-parameters.yaml → observed_value` turns those into a number at scoring
time. The projection decides what a repo *is*; the parameter file decides what
it is *worth*. That boundary is what keeps the sensitivity sweep reachable
without a code change.

## Against `docs/docs/examples/evidence-events.json`

That file is ar009's hand-authored illustration, and it predates this fixture.
Every **strength and reliability matches exactly**, all eight events. The
differences, for anyone diffing the two:

- It cites claims **c08, c10 and c21, which are not in `report-full.json`** —
  it was written against a richer draft. Same for the `cryptography` /
  `networking` skills on Terminal-Chat-Room, which that repo has no language,
  framework or topic to justify, and for the fifth `not_emitted` entry
  ("JEE Advanced rank 873").
- Its relevance values are round (`typescript: 0.9`); ours are computed
  (`0.5 + 0.5 × 184320/243920 = 0.8778`). The rule agrees — both drop CSS at the
  10% byte-share floor — only the arithmetic is exact.
- We additionally emit `react` (declared in `repo.frameworks`) and `javascript`
  (16.9% of bytes, above the floor). Open to revision; it is a modelling call,
  not a defect.

It also caught a real bug: CV claims are dated at `document.created_at`, not at
verification time. Dating the weakest evidence in the system at the moment
someone checked it would hand it perfect freshness, so a two-year-old assertion
would never decay.

## Aggregate claims

"Solved 500+ problems across LeetCode, Codeforces, GeeksforGeeks" is two things
at once: a fact Codeforces confirms (412) and an assertion nobody can check. So:

- the confirmed 412 stays on the `platform_rating` event at reliability 0.90,
  where it already was;
- the claim is emitted at `0.20 × 0.7 × 0.85 = 0.119`, discounted by two **named**
  factors (`aggregate_across_sources`, `open_bound`) so the reduction is
  explainable to the candidate;
- `payload.independently_confirmed` records which platform confirmed what, so
  6.3 can weigh the real number rather than the asserted one.

Net effect on `problem_solving`: 0.520, essentially all of it from the verified
platform. A weak event beside a strong one barely moves the posterior — which is
the behaviour you want, and a useful check that the model is doing its job.

## Tests

102 tests, `make test`, no pytest. `projector.py` is at 100% of executable lines.

| file | covers |
|---|---|
| `test_contract.py` | Schema conformance both fixtures, plus a **guard on the guard** — it injects an undeclared field and requires the schema to reject it, so conformance can't quietly become a no-op. |
| `test_invariants.py` | All six invariants **provoked**, not merely asserted on a happy path, with a control test so none can pass vacuously. |
| `test_rules.py` | Band thresholds on both sides (9/10, 49/50, 119/120, 999/1000 kB), relevance floor and clamp, ownership asymmetry. |
| `test_dates_and_links.py` | UTC-day normalisation both directions, exact repo↔claim attribution, credentials, unresolvable platforms. |
| `test_aggregate_claims.py` | Partial corroboration, both discounts, and that turning them off in YAML turns them off in behaviour. |
| `test_behaviour.py` | One behaviour each: forks suppressed, aliases, dead deployments, bare claims kept. |
| `test_golden.py` | Pins the batch to the published trace, then feeds it through `m6_model.py` to reproduce the skill graph. The only place the two modules meet. |

## Handing off to 6.2

The ingestor consumes what this produces: `POST /evidence/batch`, append-only
log, dedupe on `event_id` — which is already stable, so replay is safe by
construction. Nothing here talks to a database, a queue or a clock you don't
pass in, so it can be called inline from the ingestor or run as a worker.
