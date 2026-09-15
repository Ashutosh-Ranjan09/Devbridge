# Status — 15 September 2026

**CV Verification Engine · DevBridge M5 · day 11**

> **Feature-complete for everything reachable, every gate green.** What stands between
> this and a submittable project is not code: one decision, a larger corpus, and the
> fact that the whole thing currently exists on one machine.

---

## Scorecard

| | Today | Notes |
|---|---|---|
| **Checks** | **27 / 34** | machine ceiling; 41 catalogued − 1 excluded − 6 human |
| **Tests** | **474** passing · 484 with Postgres · 5/5 live | 0 failing |
| **Gates** | ruff ✅ · `mypy --strict` ✅ | 33 source files |
| **Size** | 33 modules · 9,959 lines · 19 test files · 5,161 test lines | |
| **Documents measured** | 3 | student · synthetic · professional |
| **Contract** | 7 fields ahead of the upstream schema | awaiting a decision |
| **Commits** | 50, since 4 Sep | **no remote** |

---

## Phases

| # | Phase | State | |
|---|---|---|---|
| 0 | Contracts | ✅ done | round-trip test restored on 8 Sep |
| 1 | Spike | ✅ done | |
| 2 | Ingest & extraction | ✅ done | PDF · DOCX · OCR · 8 passes · model routing |
| 3 | Connectors & rules | ✅ done | all reachable checks |
| 4 | Report, narrative, API, persistence | ✅ done | |
| 5 | Evaluation | ⚠️ **half** | mutation harness built; **gold set not built** |

Phase 5 specifies two instruments. The mutation engine measures whether rules
**detect** a falsified fact. The gold set — hand-labelled CVs scored for precision and
recall per claim kind — would measure whether extraction is **correct**. Only the first
exists, so extraction accuracy is currently unmeasured.

---

## Checks by group

| Group | Built | Not built | Why |
|---|---|---|---|
| D · document-intrinsic | 11 / 11 | — | |
| G · GitHub | 10 / 10 | — | G12 excluded on fairness grounds |
| P · platforms | 5 / 6 | P5 | CodeChef has no API |
| W · deployments | 1 / 2 | W2 | human — a reviewer opens the link |
| C · credentials | 1 / 5 | C1–C4 | no issuer APIs available |
| H · human | 0 / 6 | H1–H6 | by design |

---

## Gates, run today

```
ruff check src tests scripts          PASS
mypy --strict                         33 files, no issues
pytest                                474 passed · 10 skipped · 0 failed
pytest  (CVV_DATABASE_URL set)        484 passed · 0 failed
pytest -m live                        5 passed  · 3m 34s
```

The live suite has failed **once in four runs** over the past week. The cause is known
and documented — Ollama chooses the GPU/CPU layer split at load time — and a live run
now warns when `CVV_NUM_GPU` is unpinned.

---

## Measured behaviour

| Document | Claims | Filtered | Coverage | Detection | Collateral |
|---|---:|---:|---:|---|---:|
| student CV — IIT Kharagpur | 20 | 2 | 52% | **15/15** | 0 |
| synthetic CV — VIT Vellore | 20 | 1 | 44% | **7/7** applicable | 1 |
| professional CV — 2 pages | 15 | 6 | 22% | **2/2** applicable | 0 |

- **Zero claims dropped at grounding on all three.** Every loss is the gate refusing
  real text, not the model inventing it.
- **Collateral 1 on the synthetic CV is correct**: stretching a degree to 2020–2027 also
  genuinely contradicts a 2021 admission year.
- **The professional CV's 22%** is mostly structural — it names no GitHub repository and
  no competitive-programming account, so 13 of 15 mutations have nothing to act on.
  The document-intrinsic checks all ran.

---

## Since the last audit (8 Sep)

| Area | Change |
|---|---|
| **Contract** | round-trip test restored; five fields the schema defines and we lacked, added |
| **Architecture** | purity and isolation rules now enforced by an AST-walking test |
| **Third CV** | slash-date convention inferred from the whole document; D5 handover band (a 13-day notice period is not a contradiction); D2 split into ungroundable vs. filtered |
| **Narrative** | the model echoed the rule id into every sentence; a prompt instruction did nothing on two models, so it is now stripped in code |
| **Documentation** | design record (`docs/design.md`, `.html`, 35-page `.pdf`) including a 14-stage worked example |

---

## Decisions needed

### 1. Seven fields ahead of the contract

25 of 27 upstream schema definitions set `additionalProperties: false`, so these make
our output invalid for a consumer validating against that schema:

`ExtractionMeta.filtered` · `RepoEvidence.authored_files` · `RepoEvidence.authored_bytes`
· `RepoEvidence.homepage` · `GitHubEvidence.public_repos` ·
`GitHubEvidence.public_repo_count` · `RuleOutcome.note`

Each is load-bearing for a check. The integration spec prescribes
`schemas/*.schema.json — generated from Pydantic, committed`, which reads as: our
models are the source of truth, and the upstream draft is what gets regenerated.

**Recommended:** generate `contracts/schemas/` from the models at version `2.0.0` and
retire the extension list. Needs your call because it changes what "the contract" means.

### 2. Non-competitive-programming achievements

The achievements pass asks only about contests and ratings. On the professional CV,
six real claims — patents, 38K GitHub stars, published books — were extracted and then
correctly refused as unattributable. They are lost, not wrong.

"38K GitHub stars" is checkable: the API reports stargazer counts. **This would be a new
check, not a fix** — which is why it is here rather than done.

---

## Risks

| | Risk | Severity | Why |
|---|---|---|---|
| 1 | **No git remote** | 🔴 high | 50 commits and 11 days of work exist on one laptop. A disk failure loses the project |
| 2 | **Personal data in git history** | 🔴 high | blocks any public push as-is — see below |
| 3 | **Response cache tracked in git** | 🟠 medium | 21 files since 5 Sep; every run dirties the tree |
| 4 | **Extraction accuracy unmeasured** | 🟠 medium | no gold set — the thesis can quote detection but not extraction quality |
| 5 | **Three-document corpus** | 🟠 medium | each new document found a real bug within minutes |
| 6 | **Live-suite flake** | 🟡 low | known cause, now self-diagnosing |

### Risks 1–3 interact

The obvious fix for risk 1 — push to GitHub — is blocked by risks 2 and 3 **if the
repository is public**:

| Tracked file | Contains |
|---|---|
| `docs/CV-SDE-AR.pdf` | the author's CV: name, roll number, handles, institutions |
| `docs/demo_resume.pdf` | a second person's CV |
| `docs/design.pdf` | the worked example — roll number 6×, Codeforces handle 12×, GitHub account 4× |
| `.cache/http/github/*.json` | 21 raw GitHub API responses about the candidate's account |

`.gitignore` does not cover `.cache/`, which is how the cache got committed on 5 Sep
along with the GitHub connector.

**Recommended order:**

1. **A private remote, today.** Solves the backup risk without exposing anything.
2. **Stop tracking the cache**: add `.cache/` to `.gitignore` and `git rm -r --cached .cache`.
   Non-destructive — the files stay on disk.
3. **Before anything goes public**, remove the CVs and the cache from history. That is a
   history rewrite (`git filter-repo`), it is destructive and it changes every commit
   hash, so it should be a deliberate step rather than a side effect of a cleanup.

---

## Housekeeping found today

| Item | Detail |
|---|---|
| **A stack claim that is wrong** | CLAUDE.md lists `pydantic-ai → ollama` as the LLM layer and warns to verify pydantic-ai passes `num_ctx` through. **pydantic-ai is not installed**: `providers.py` calls Ollama's HTTP API directly with `httpx`, and sets `num_ctx` explicitly on every call. The warning is moot and the stack line is inaccurate |
| **Stale counts** | CLAUDE.md and README say 466 tests; it is 474 |
| **Stack entries not yet installed** | qdrant, pandas, matplotlib, selectolax — correctly deferred to later phases in `pyproject.toml`, but listed in CLAUDE.md's stack as though present |
| **Deprecation warnings** | two, both third-party: `starlette.testclient` over `httpx`, and an `anyio` alias. Not ours; revisit on the next dependency bump |

---

## Next, ranked

| | Work | Effort | Unblocks |
|---|---|---|---|
| 1 | Private git remote | 10 min | removes the single largest risk |
| 2 | Untrack `.cache/`, fix `.gitignore` | 5 min | clean tree after every run |
| 3 | Decide the contract (§ Decisions 1) | a conversation | retires the extension list |
| 4 | Correct CLAUDE.md's stack and counts | 10 min | future sessions start from true context |
| 5 | **Gold set** — 10–20 hand-labelled CVs | days | the missing half of phase 5; extraction metrics for the thesis |
| 6 | More real CVs, other institutions | ongoing | every one so far has found a bug |
| 7 | History rewrite, if going public | 30 min + care | a public repository |

Items 1, 2 and 4 are small enough to do in one sitting. Item 5 is the only remaining
work that is genuinely large, and it is what the evaluation chapter needs.
