# m6_scoring — scoring engine

**Status: complete (v1.0.0).** M6 submodule 6.3.

The plan's weeks 5–7: *observation model, Kalman update, decay kernel,
recompute-from-log*, with propagation from week 8. Reproduces
`contracts/reference/m6_model.py` exactly — same mathematics, but every constant
read from `contracts/m6-parameters.yaml` instead of hard-coded.

**No trained models. No optimiser. No labelled data. Closed-form updates only.**

```python
from m6_scoring import ScoringEngine
engine = ScoringEngine(ontology=default_ontology())
state  = engine.fold(events, "typescript", as_of=date(2026, 8, 24))
print(engine.explain(state))
```

```
make score                      # the whole graph from the evidence log
make explain SKILL=typescript   # one skill, decomposed
make recover                    # the gate
make sweep                      # every parameter the sweep may vary
```

## Layout

| | |
|---|---|
| `params.py` | Reads `m6-parameters.yaml`. Engine takes `value`, sweep takes `sweep`. Swept parameters are **discovered** by walking the YAML, so adding one to the contract needs no code change. |
| `observation.py` | Event → `(observed, variance)`. The boundary the projection left open. |
| `filter.py` | State, decay, Kalman update, score. Logit space throughout. |
| `engine.py` | Fold-from-log, `SkillState`, ablation, `explain`. |
| `propagation.py` | Read-time, one hop, direct-evidence sources only. |
| `recovery.py` | Parameter-recovery simulation — the plan's gate. |

## The observation model

This is the piece nothing implemented before: an `EvidenceEvent` carries no
`observed` field (`additionalProperties: false`), so the projection emits raw
facts in `payload` and the number is computed here from the contract. Four
methods, all declared in YAML: flat constants, substance bands, proficiency
bands, and `a + b · ECDF(rating)` for platform ratings.

Two quantities, and keeping them apart is the design:

- **observed** — what this evidence says the ability *is*
- **variance** — how much to believe it: `S0 / (reliability × relevance × strength)`

**Relevance is epistemic.** A repository that is 60% TypeScript is not evidence
of *worse* TypeScript ability; it is *weaker evidence* about it. So relevance
goes in the variance and never in the observed value — `test_observation.py`
asserts exactly that.

An event the model cannot price raises `UnscoreableEvent` rather than taking a
default. A silently-defaulted observation is a score nobody can explain, and
there is no overall trust number here to hide it behind.

## The recovery gate

> *"if the filter cannot recover a known ability from synthetic evidence,
> nothing downstream is worth building"*

`make recover` invents developers with known abilities, generates noisy evidence
through the same variance formula the engine uses, folds it with the real filter,
and asks whether the truth comes back:

```
parameter recovery — 300 trials x 12 events
  bias      -0.0236   (want |bias| < 0.05)
  rmse       0.0510   (want < 0.15)
  coverage   0.677    (truth inside mu ± z·sigma)
  PASS

   1 events  rmse 0.1356      16 events  rmse 0.0436
   4 events  rmse 0.0756      32 events  rmse 0.0350
```

Two things worth noting. Coverage lands at **0.677** against the nominal 0.682
for ±1σ — the filter's stated uncertainty is close to its actual uncertainty,
which is not something the design guaranteed. And the bias is **negative**: the
estimate runs slightly low, pulled by the deliberately-below-median prior. That
is the right direction to be wrong in, and a test enforces the sign.

Seeded, so a regression is a changed number rather than a flake. Recovery also
passes under a doubled prior width and across the full swept range of `S0`.

## Recompute-from-log

State is a **derived cache, never a source of truth** (O4). Every score comes
from folding the immutable log in `(occurred_at, event_id)` order, which is what
makes three things nearly free:

- **`as_of` queries** — the graph at any past date, just a shorter fold
- **ablation** — `fold_without(origin="github_api")`; the report's per-source
  table is that in a loop
- **the sweep** — a different `Parameters`, same fold

`rehydrate()` is the cheap read path (decay a cached state instead of re-folding),
and a test asserts the two agree to 1e-5 — if they didn't, the cache would be a
second, quietly different answer. A state from another `parameter_version` is
refused: mixing two parameter sets makes the ordering meaningless, and the
ordering is the product.

## Propagation, and a problem it exposes

Read-time, one hop, direct-evidence sources only. A neighbour enters as a
pseudo-observation with variance inflated by `1/γ`, so damping reuses the
observation mechanism rather than adding a second one — weak evidence and distant
evidence are the same kind of thing.

The seed ontology's `cpp → c` edge reproduces the published trace's propagated
`c ≈ 0.37`. It also reproduces the **presentation problem** flagged earlier: `c`
outranks `python` (0.189) on no direct evidence at all. The engine's answer is to
make that visible — `evidence_count: 0`, `prior_only: true`, and a `propagated`
block naming the source, edge type and γ — not to clamp the number. Clamping
would be lying about the model rather than improving it. A test pins this as
documented behaviour so nobody "fixes" it by accident.

## Tests — 133 in this package

| file | covers |
|---|---|
| `test_params.py` | Every constant reachable; sweep discovery; **the two contracts agree about every shared skill tier** (a skill silently changing tier changes its half-life tenfold). |
| `test_observation.py` | All four methods; ECDF monotone and matching the contract's worked example; relevance in variance not value. |
| `test_filter.py` | Structural properties, not magic numbers — variance never rises on update, the estimate never overshoots, updates commute, decay pulls *toward* the prior from both sides. |
| `test_engine.py` | Fold determinism, `as_of`, ablation, schema conformance, cheap-read-path parity, explain shape. |
| `test_propagation.py` | One hop enforced, cycles terminate, direct evidence never overwritten, damping weakens. |
| `test_recovery.py` | The gate, plus convergence, bias sign, and robustness to swept parameters. |
| `test_reference_parity.py` | Prior, update, decay, variance, fold, explain and propagation all matched against `m6_model.py` to 1e-9. |
| `test_pipeline.py` | Report → projection → ingestor → scoring over real storage. |

## One thing to fix before publishing results

`contracts/reference-distributions.yaml` holds the Codeforces ECDF the
`platform_rating` observation needs. Its anchors are **approximated** from the
published rank boundaries, not computed from the user list — the file says so in
its own `status` field, and a test asserts that admission stays there. Regenerate
it (`/api/user.ratedList`, one rating per handle, sort, emit the empirical CDF)
before any number from this engine goes in the report. `platform_rating` is the
strongest event kind in the system at reliability 0.90, so an error there matters
more than an error anywhere else.

The table is per platform: a rating is priced from `<platform>_rated_ecdf`, and a
platform with no table is refused with `UnscoreableEvent`. Codeforces is the only
one. The projection keeps the two in step — it emits `platform_rating` only for
`rating_reference.platforms`, and a test fails if one of those has no table.
