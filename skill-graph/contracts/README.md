# contracts/

Machine-readable contracts for DevBridge M6 and the event projection module.
Human-readable reasoning lives in `docs/m6-decisions.html` — read that first
if you want to know *why* any value here is what it is.

| File | What it fixes |
|---|---|
| `m6-parameters.yaml` | Every constant in the scoring model, with a sweep range and a rationale. Code reads `value`; the sensitivity sweep reads `sweep`. |
| `projection-rules.yaml` | ClaimGraph + EvidenceBundle + FindingsReport → EvidenceEventBatch. Emission rules, reliability factors, suppressions, invariants. |
| `schemas/skill-state.schema.json` | The persisted (μ, σ²) state. A derived cache, not a source of truth. |
| `reference/m6_model.py` | Executable specification of the model — dependency-free, ~120 lines. The real 6.3 scoring-engine must reproduce its numbers. |

`projection-rules.yaml` is **implemented** by `packages/m6_projection/` (v1.0.0,
complete; 102 tests, `make test`). That package hard-codes no threshold: edit
this contract and the module's behaviour changes with it, which is what keeps the
sensitivity sweep reachable without a code edit. If you change a value here, run
`make test` — the golden test will tell you which published document is now
stale.

## Rules

1. **`m6-parameters.yaml` is the only place a constant may live.** No magic numbers
   in service code. The sweep and the engine read the same file, so they cannot
   drift apart.
2. **Changing a parameter invalidates every stored `SkillState`.** That is why
   `provenance.parameter_version` exists. Bump it and recompute; never mix.
3. **Nothing here is fitted.** Values are set from documented reasoning and
   validated by sensitivity sweep and parameter-recovery simulation. If you find
   yourself tuning a constant to make one candidate look right, stop.
4. **The reference implementation is the tie-breaker.** If prose and code
   disagree, the code is what was actually decided; fix the prose.

## Input contract

M6 reads exactly one thing: an `EvidenceEventBatch` validating against
`../schemas/evidence-event.schema.json`. It does not read the ClaimGraph.
`../schemas/examples/evidence-events.json` is fixture one.
