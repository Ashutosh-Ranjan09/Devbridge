# m6_query — query API

**Status: complete (v1.0.0).** M6 submodule 6.4.

The plan's weeks 9–10: *skills endpoint, /explain to the fixed response shape,
as_of*. It also says the explain endpoint is the demo and should be built as a
first-class deliverable, so it is — it carries the contributing events with their
weights, the decay story, and what was considered and left out.

```
make query                       # the graph as the API presents it
make demo SKILL=typescript       # the explain response
make find SKILL=typescript MIN=0.3
make api                         # serve on :8200
```

| endpoint | |
|---|---|
| `GET /health` | Liveness, population size, parameter version. |
| `GET /skills` | The ontology with volatility tiers and half-lives, for a filter UI. |
| `GET /developers/{ref}/skills` | The graph. `propagate`, `include_inferred`, `min_evidence`. |
| `GET /developers/{ref}/skills/{skill}/explain` | The demo. |
| `GET /search?skill=…&min=…&definite=…` | Tiers, never a ranking. |
| `GET /developers/{ref}/score` | **400**, on purpose. |

Every endpoint takes `as_of=YYYY-MM-DD`.

## Two constraints shape every response

**No overall trust score.** Not merely unimplemented — refused, with a reason,
across four spellings (`score`, `rating`, `trust`, `overall`). A single number
invites exactly the ranking-by-vibe the evidence model exists to avoid, and it
cannot be explained the way a per-skill interval can. `test_constraints.py` walks
every response looking for aggregate-shaped keys, and checks no public method on
`QueryService` is named anything a future contributor might reach for.

**Only definite interval overlap.** Two candidates may be ordered only when
their credible intervals do not overlap. So search returns a **partial order**:
tiers of candidates nobody can separate, with the tiers themselves strictly
ordered and every split justified by a non-overlapping pair. Inside a tier the
sort is alphabetical, deliberately — ordering by point score there would
recreate the false precision the tiers exist to prevent. The serialised row
carries `interval`, never a bare `score`, for the same reason.

Search takes `definite` as an explicit parameter rather than defaulting quietly:
`true` means the whole interval clears the bar (confident they are above it),
`false` means it reaches the bar (they might be). That is a recruiter's risk
decision and the API should not make it for them.

## The finding worth reading

**At z=1, search cannot rank — it can only filter.** This is not a defect; it is
what the constraint costs, and it is pinned by two tests so it cannot drift
unnoticed.

Four synthetic candidates — full evidence, thin evidence, and the same evidence
at a *third* of the reliability — all land in **one indistinguishable tier**.
Two things cause it:

1. **Reliability barely moves the estimate.** subj_weak's mean sits within 0.05
   of subj_strong's. That is correct Bayesian behaviour: reliability governs how
   *confident* the filter is, not *where* it lands. Only a different observed
   value moves the estimate. Anyone expecting low reliability alone to demote a
   candidate is expecting the wrong thing from the model.

2. **The bands are wide relative to real differences.** A candidate whose
   repositories are all *trivial* rather than *substantial* — a genuine
   difference worth ~0.10 of mean ability — still overlaps at z=1. Measured: that
   pair separates at **z ≤ 0.40** and not at 0.45.

So if the product needs search to rank, the lever is `display.z` (swept 0.5–2.0
in the contract), and lowering it means accepting false precision. That trade
belongs in the sensitivity chapter, not in a quiet code change — which is why
`test_the_same_pair_separates_once_the_bands_are_narrow_enough` asserts the 0.40
threshold directly.

## The explain response

```json
{ "skill": "typescript", "score": 0.381, "interval": [0.381, 0.626],
  "mean": 0.504, "sigma": 0.123, "sigma_logit": 0.501,
  "basis": "direct_evidence", "evidence_count": 3,
  "days_since_newest_evidence": 431, "half_life_days": 1167,
  "contributions": [ { "event_id": "ev_da5e3e177297", "kind": "repo_artifact",
                       "observed": 0.66, "relevance": 0.878, "weight": 0.789 }, … ],
  "not_counted": [ { "what": "W1 — …vercel.app returns 404",
                     "reason": "not_a_capability_signal" }, … ] }
```

`not_counted` is the one addition beyond 6.3's shape. The projection records
every suppression in `not_emitted[]`; surfacing it here is what lets a candidate
see that a claim was *read and rejected* rather than never noticed — the "silence
is never an option" invariant carried all the way to the user-facing response.

A propagated skill returns `basis: "propagated"`, `evidence_count: 0`, empty
`contributions`, and the `propagated` block naming the source and γ. That is the
settled answer to the presentation problem: `c` outranks skills with real
evidence, and the response says plainly that it is an inference.

## Tests — 97 in this package

| file | covers |
|---|---|
| `test_ranking.py` | The tiering rule in isolation: touching intervals do not separate, a wide interval is above nothing, splits are justified, tiers are order-independent. |
| `test_service.py` | Skills, `as_of` in both directions, and explain as the demo — including that the first event carries the most weight against a wide prior. |
| `test_search.py` | Tiers, thresholds, inferred results opt-in, and the two z-threshold findings above. |
| `test_constraints.py` | The hard constraints as executable assertions — no aggregate key in any response, no aggregate-shaped method name, every split justified. |
| `test_api.py` | Real sockets, status codes, four refusal spellings, and eight concurrent readers returning identical scores. |

## Handing off

6.5 integrity-analytics is the last submodule and the plan marks it *"if time
allows"*. The more valuable next step is probably the **sensitivity sweep and
ablation table** (plan weeks 11–12): `Parameters.sweepable()` already enumerates
every swept constant, `ScoringEngine.fold_without()` already does per-source
ablation, and the z-threshold finding above is the first result that chapter
needs.
