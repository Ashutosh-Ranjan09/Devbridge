# DevBridge — Module 6: the Verified Skill Graph

B.Tech project. DevBridge's M5 (CV verification) checks a CV against GitHub, competitive-
programming platforms, deployments and credential issuers, and emits a `VerificationReport`.
**This repo implements M6**: it turns that report into a per-skill estimate of ability, with
an interval for uncertainty, that decays as evidence ages and can be explained event by event.

**Status: implemented and complete (all packages v1.0.0).** 572 tests pass. M5 lives beside
it in `../cv-verification`, and M6 only ever reads M5's output document — the
`verification-report.json` that `cvv verify --save` writes. Both read the contract from
`../schemas/`.

Full human guide (40 pages, worked numbers): `docs/reports/module6-complete-guide.pdf`.

## Commands

Python 3.12. Third-party deps: `pyyaml`, `jsonschema` only. Everything else is stdlib.
**pytest is not needed.** Every command needs `PYTHONPATH=packages`, which the Makefile sets.

```
make test [FILTER=substr]   # zero-dependency runner tests/run.py — expect "572 passed, 0 failed"
make demo                   # narrated 9-step walkthrough → demo/output/01..05-*.json
make demo-http              # same, plus every HTTP endpoint on an ephemeral port
make all                    # test + ontology check + verify + recover + demo
make project|ingest|score|query      # one submodule at a time on ../schemas/examples/report-full.json
make why SKILL=cpp          # explain one skill   (NOT `make explain` — that target doesn't exist)
make find SKILL=typescript MIN=0.3
make recover                # parameter-recovery gate (exit 1 on fail)
make sweep                  # list swept parameters
make serve / make api       # ingestor :8100 / query API :8200 on evidence.db
make clean
```

Combined single-process server (adds `POST /evidence/report`, `/versions`, `/integrity`,
`/profile`): `from m6 import M6; from m6.api import serve; serve(M6("evidence.db"), port=8300).serve_forever()`.

## Architecture

```
report --6.0--> events --6.2--> log --6.3--> states --6.4--> answers
                                 |                             ^
                                6.1 ontology ------------------+
                                 |
                                6.5 reads the log and the states, writes nothing
```

| | package | job |
|---|---|---|
| 6.0 | `m6_projection` | M5 report → `EvidenceEventBatch`. Decides what a verified artefact *is*. Deterministic. |
| 6.1 | `m6_ontology` | skills, tiers, edges from `../schemas/skills/ontology.yaml` (35 skills, 15 edges, v0.2.0) |
| 6.2 | `m6_ingestor` | schema validation, idempotency, quarantine, append-only SQLite log |
| 6.3 | `m6_scoring` | observation model, Kalman update, decay, propagation, recovery gate |
| 6.4 | `m6_query` | skills, explain, tiered search, HTTP |
| 6.5 | `m6_integrity` | nine checks about the *shape* of the evidence; changes no score |
| — | `m6` | `M6` facade + combined HTTP server. Must agree byte-for-byte with calling submodules directly |

Dependencies point one way. Ports are deliberately narrow:
- 6.2 sees the ontology only through `SkillResolver` = `knows()` + `ontology_version`. Don't widen it, because a test enforces this.
- 6.4 reads the log via `events_for_skill()` / `resolved_skills()`. These exclude quarantined skills, so quarantine also holds on the read path.
- 6.0 and 6.3 meet only through the event schema. The projection emits **facts** in `payload` (e.g. `substance_band`), and 6.3 turns them into numbers via `m6-parameters.yaml`. Events have no `observed` field (`additionalProperties: false`).

## Hard constraints — do not re-litigate

1. **No trained models.** No ML, optimiser or labelled data. Closed-form updates and
   descriptive statistics against reference tables only. Constants come from documented reasoning,
   are validated by the sweep and recovery simulation, and are never tuned to make one candidate look right.
2. **No overall score.** No number summarises a person. `/developers/{ref}/score|rating|trust|overall`
   returns **400** with a reason. `test_constraints.py` scans responses and method names for
   aggregate-shaped keys, so don't add one, even for demo prep.
3. **Intervals, never bare points.** The published `score` is the **lower bound**, and every row
   carries `interval`. Two candidates are ordered only when their intervals don't overlap, so search
   returns **tiers**, alphabetical inside a tier.
4. **Append-only log, scores are derived.** DB triggers block UPDATE/DELETE. State is a cache that
   is always recomputable by folding the log in `(occurred_at, event_id)` order.
5. **Constants live only in `contracts/`.** No magic numbers in Python. The engine reads `value`
   and the sweep reads `sweep` from the same file.
6. **Silence is never an option.** Every claim ends up either on an event or in `not_emitted[]` with one of five
   schema reasons. `_check_invariants` raises if a claim is unaccounted for.
7. **Integrity never moves a number.** 6.5 produces findings, with `notice` or `attention` only and no "fail".
   Each finding names its evidence and states an innocent explanation. `test_neutrality.py` asserts that the graph is
   byte-identical with and without 6.5.

## The model in one screen (all in logit space; display = sigmoid)

```
prior            μ0 = logit(0.25) = −1.0986,  σ0² = 1.69          # below median, wide
observed value   per kind from m6-parameters.yaml observed_value   # display space, clamp [0.01,0.99]
                 platform_rating = 0.50 + 0.40·ECDF(max_rating); repo bands 0.35/0.50/0.62/0.66;
                 claim_corroborated 0.68; artifact_live 0.58; credential 0.70;
                 cv_claim by proficiency 0.30/0.45/0.60/0.75; claim_contradicted 0.15
obs variance     σ²obs = S0 / (reliability × relevance × strength),  S0 = 0.10
update           k = σ²/(σ²+σ²obs);  μ += k(logit(obs) − μ);  σ² ×= (1 − k)
decay (Δt days)  σ² += λ_tier·Δt;   μ += (μ0 − μ)(1 − e^(−Δt·λ/k_h)),  k_h = 0.35
                 λ: fundamental 1e-4 · ecosystem 3e-4 · framework 7.5e-4   (h = 0.35/λ: 3500/1167/467 d)
display          score = σ(μ − zσ), upper = σ(μ + zσ), mean = σ(μ), z = 1
                 explain.sigma = mean − score (display); sigma_logit = σ (state)
propagation      read time, ONE hop, sources with direct evidence only, direct evidence always wins;
                 pseudo-observation with σ²obs = σ²_source / γ_type
                 γ: REQUIRES 0.65 · PREREQUISITE_OF 0.55 · RELATED_TO 0.40 (one γ per TYPE, never per edge)
```

- **Relevance is epistemic.** It goes in the variance, never in the observed value.
- Reliability = base × named factors (`ownership_unverified` 0.6 for positive evidence only, `scraped_source` 0.7,
  `aggregate_across_sources` 0.7, `open_bound` 0.85). Each applied factor is written on the event.
- `stale_evidence` is deliberately 1.0, because decay already handles staleness.
- Uncorroborated CV claims are dated at the **CV's** `created_at`, not at verification time.
- `event_id = "ev_" + sha256(verification_id|kind|discriminator)[:12]`, so a replay is a no-op. The same id with
  different content is a 409 conflict, never an update.
- An unknown skill is quarantined **per skill**: the event is stored and still counts for its known skills.
- A propagated skill has `evidence_count: 0`, `basis: "propagated"` and a `propagated{from, edge_type, gamma}`
  block. The fix for "c outranks python" is to label it, never to clamp the number.
- An event that can't be priced raises `UnscoreableEvent`. Never default.

## Contracts (the source of truth)

| file | read by | fixes |
|---|---|---|
| `contracts/m6-parameters.yaml` | 6.3 | every scoring constant + sweep range. `contract_version` → `parameter_version` |
| `contracts/projection-rules.yaml` | 6.0 | emission rules, strengths, base reliabilities, factors, bands, suppressions, the manifest rule |
| `../schemas/skills/ontology.yaml` | 6.1, and M5 | skills, tiers, edges — **shared with M5's skill resolver**. Grow it by PR; `python -m m6_ontology check` validates it |
| `../schemas/skills/aliases.yaml` | 6.0, and M5 | other names for skills. Grown by `cvv aliases --promote` after review |
| `contracts/integrity-rules.yaml` | 6.5 | the nine checks; deleting one switches it off |
| `contracts/reference-distributions.yaml` | 6.3 | per-platform rating ECDFs, `<platform>_rated_ecdf` — Codeforces only (data, not a parameter) |
| `contracts/reference/m6_model.py` | tests | ~120-line executable spec. Engine must match to 1e-9; **if prose and this disagree, this wins** |
| `../schemas/evidence-event.schema.json` | 6.2 | M6's input contract |
| `../schemas/verification-report.schema.json` | demo tests | M5's output contract |

Changing a parameter invalidates stored `SkillState`s, so bump `contract_version` and recompute.
Never mix states from two parameter sets. `rehydrate()` refuses to.

## Working in this repo

- Match the existing style: dense, reasoning-first docstrings and comments explaining **why**;
  frozen/slotted dataclasses; pure functions in `rules.py`; errors as distinct types that map to HTTP status.
- New behaviour goes in the contract YAML first, and code reads it. Adding a swept parameter needs no code,
  because `Parameters.sweepable()` walks the YAML.
- Tests live in `tests/m6_<pkg>/`. Helper module names must be unique across packages, because the runner fails on
  collisions. Each check or invariant gets a positive and a negative case, and invariants are *provoked*.
- If you change projection behaviour, `test_golden.py` and `tests/m6_whole/test_demo.py` (which checks the demo
  README's numbers) will tell you which published numbers went stale.
- SQLite is kept to SQL that Postgres also accepts, because Postgres is the agreed target. One re-entrant lock serialises
  all DB access, and the whole ingest decision is held exclusively, as the concurrency tests require.
- **No `m5-` assumptions in M6 code.** M4 (assessments) will feed this graph later. When it does, the change is
  additive: add `assessment_result` to the `kind` enum, widen `source.module` from `const` to an enum,
  and add priors plus an observed-value rule (`context_difficulty` is already reserved). Don't pre-build it.
- Design artifacts: publish each revision as a **new** artifact. Never overwrite one, because the revision history matters.

## Known gaps / gotchas

- `claim_contradicted` is defined in the schema, parameters and 6.3/6.5, but **`projector.py` never emits it**,
  so `CONTRADICTED` can't fire on real input yet.
- The Codeforces ECDF is **approximated** (`status: approximated_pending_regeneration`). Regenerate it from
  `/api/user.ratedList` before publishing any number, because `platform_rating` is the strongest event (reliability 0.90).
- **A report's `skill_resolution` is read first.** M5 maps every skill name to an id from
  the shared list, or none (rules, cache, then a closed-choice model call). 6.0 uses that,
  and its own `normalise_skill` — spelling variants checked against `knows()` — only for a
  name the report does not cover. An event whose skill came only from a model mapping
  carries `payload.mapped_by_model`; the numbers are unchanged. The model runs in M5, so M6
  still contains none.
- **A manifest credits only dependencies that are skills** (`manifest_dependencies.known_only`).
  The rest are named once per repository in `not_emitted` as `no_skill_mapping`, not carried
  into quarantine — seventy npm packages are libraries, not skills awaiting an ontology entry.
- **One claim naming a skill twice** ("Next.js | next") is deduplicated after resolution.
  Before, the colliding event ids made `_check_invariants` refuse the whole report.
- Consent was removed as out of scope for this project: no gate in 6.0, no check in 6.2.
  `consent_scope` survives as an optional schema field and a log column, always empty.
- **CodeChef has no rating distribution**, so a CodeChef rating never reaches 6.3 as a
  `platform_rating`: it confirms a claim it reaches (`claim_corroborated`, scraped discount),
  else it is suppressed. A platform listed in `rating_reference.platforms` must have a table;
  a test enforces it.
- **A skill claim is corroborated only by repository languages, never by a platform rating**,
  though the contract's `claim_corroborated` rule names both. So "competitive programming" and
  "data structures and algorithms" have no alias: as `cv_claim`s at 0.45 they would pull down
  an `algorithms` estimate a Codeforces rating had already set.
- `claim_corroborated` observes a flat 0.68, which sits below a Specialist's 0.739, so a
  CodeChef confirmation pulls `algorithms` down slightly.
- `commit_count: null` (M5 sends it for repos it read file by file) is unknown, not zero:
  substance-band conditions over an unknown value are skipped.
- `half_life_days` (h = k/λ) is actually the e-folding time constant. The true half-life is h·ln2.
- `ranking.tiers()` starts a new tier when a candidate's upper bound < the current tier's lowest lower bound.
  A later candidate can still overlap a member of an earlier tier.
- At z = 1 search mostly *filters* rather than ranks. A real ~0.10 ability gap only separates at z ≤ 0.40.
  The lever is `display.z`, at the cost of false precision. Two tests pin this.
- Docstrings in `m6_query/api.py` and `m6/api.py` say `/score` returns 410, but the code and tests return **400**.

## Where to read more

- `docs/m6-decisions.html`: decisions O1–O7 with rejected alternatives (why each value is what it is)
- `docs/m6-worked-trace.html`: the golden report traced end to end
- `packages/*/README.md`: per-submodule design notes and test inventories
- `demo/README.md`: what each demo step is meant to show
- `conversation-log.md`: the full M5 design discussion (index table + "five reversals" section first).
  Kept outside this repository, in `discussion-ar/docs/` beside it.
  Broader settled constraints: GitHub/CP APIs are the core evidence source, and the LLM translates but never judges.
