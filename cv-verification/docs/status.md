# Status — 25 October 2026

**CV Verification Engine · DevBridge M5**

> **Every check in scope is built, and every gate is green.** What stands between this
> and a submittable project is not code: a backup, a larger corpus, and one decision
> about the contract.

---

## Scorecard

| | Today | Notes |
|---|---|---|
| **Checks** | **31 / 31 in scope** | 30 rules + the narrative (C5). 43 catalogued − G12 excluded − C1–C4 out of scope − W2, H1–H6 human. D13 and D14 added 29 Oct: hidden text, extraction coverage |
| **Tests** | **611** passing · 621 with Postgres | 0 failing; 5 live tests deselected by default |
| **Gates** | ruff ✅ · `mypy --strict` ✅ | 33 source files |
| **Size** | 33 modules · 11,468 lines · 23 test files · 6,577 test lines | |
| **Model backends** | 2 | Ollama (`qwen3:1.7b`, default) · Claude via the local Claude Code wrapper |
| **Documents measured** | 3 | only the student CV since October |
| **Contract** | 10 fields ahead of the schema | awaiting a decision |
| **M6 handoff** | ✅ live, end to end | `cvv verify --save` → `verification-report.json` → `../skill-graph` |
| **Commits** | 82, since 4 Sep | **no remote** |

---

## Checks by group

| Group | Built | Not built | Why |
|---|---|---|---|
| D · document-intrinsic | 13 / 13 | — | |
| G · GitHub | 10 / 10 | — | G12 excluded on fairness grounds |
| P · platforms | 6 / 6 | — | P5 reads CodeChef's profile page — scraped, so attention-only |
| W · deployments | 1 / 2 | W2 | human by design — a reviewer opens the link |
| C · credentials | 1 / 5 | C1–C4 | out of scope for this project |
| H · human | 0 / 6 | H1–H6 | by design; `--worksheet` prepares them |

---

## Gates, run today

```
ruff check src tests                  PASS
mypy --strict                         33 files, no issues
pytest                                611 passed · 10 skipped (Postgres-only) · 0 failed
cvv evaluate docs/CV-SDE-AR.pdf       18/18 detection · 0 collateral
```

---

## Measured behaviour

| Document | Claims | Filtered | Coverage | Detection | Collateral |
|---|---:|---:|---:|---|---:|
| student CV — IIT Kharagpur (29 Oct, Claude baseline of 21 Oct) | 19 | 0 | 57% | **18/18** | 0 |
| student CV — IIT Kharagpur (21 Oct, Claude) | 19 | 0 | 57% | **17/17** | 0 |
| synthetic CV — VIT Vellore (15 Sep) | 20 | 1 | 44% | **7/7** applicable | 1 |
| professional CV — 2 pages (15 Sep) | 15 | 6 | 22% | **2/2** applicable | 0 |

- **The student CV now contradicts nothing.** Three questions remain, each printed
  with its benign reading: P2 (rank 1106 claimed, 1109 recorded — a standings-timing
  artefact), G3 (the GitHub account is inferred, not proven), D3 (the institution's
  own disclaimer).
- **CodeChef corroborates**: highest rating 1746 against the claimed 1733, and P6
  now sees one handle, `ar009`, on Codeforces and CodeChef.
- **The other two rows predate October.** They should be re-run before they are
  quoted alongside the first.

---

## Since 15 September

| Area | Change |
|---|---|
| **Second model backend** | `CVV_LLM_BACKEND=claude-code` sends each pass to Claude through the local Claude Code wrapper. Same seam, same filters. On the reference CV: 73s vs 98s, nothing filtered, cleaner stacks; it missed the "500+ problems" aggregate. Not seeded, so not reproducible |
| **Seven fairness fixes** | each would have flagged an honest CV: G4 investigated `apache` as the candidate; D9 decoded any roll-number-shaped token with IIT Kharagpur's table; D10 called a return internship a contradiction; W1 called a timeout a dead site; P2 matched `10` inside "1106"; G6 contradicted with no manifest read; D9 lost a finding when it then abstained |
| **P5 — CodeChef** | the public profile page, scraped: peak rating, contest ranks by name, problems solved. Attention-only. A missing handle is a finding only when CodeChef redirects home; any other redirect is a "site changed" gap |
| **Three bugs** | D7/G6/G9 lost a second finding on one claim (shared id); the narrative was rejected whenever a rule fired twice; `POST /v1/verifications` ignored a JSON body and multipart `options` |
| **Scope** | C1–C4 out of scope; W2 human by design; consent handling removed from M5 and M6 |
| **Skill resolution** | a third model call site: each skill name in the report mapped to one id from the shared `schemas/skills/` list, or none, after rules and a cache; `cvv aliases` to review and promote. G6 and G9 no longer match `java` to JavaScript. M6 reads the mapping, credits only manifest dependencies that are skills, and no longer refuses a report naming one skill twice |
| **One repository** | `devbridge/` holds M5 (`cv-verification/`) and M6 (`skill-graph/`) side by side, with one copy of the contract (`schemas/`) and of the design pages (`docs/`) |
| **The M6 handoff** | the report is now the contract's whole `VerificationReport`, written by `--save`; PDF dates are ISO 8601; `events.py` removed, since M6 projects the report itself. Found by running a real report through M6, which also exposed four M6 bugs, fixed there |

---

## Decisions needed

### 1. Ten fields ahead of the contract

25 of 27 upstream schema definitions set `additionalProperties: false`, so these make
our output invalid for a consumer validating against that schema:

`ExtractionMeta.filtered` · `RepoEvidence.authored_files` · `RepoEvidence.authored_bytes`
· `RepoEvidence.homepage` · `GitHubEvidence.public_repos` ·
`GitHubEvidence.public_repo_count` · `RuleOutcome.note` · `Narrative.rejected_because` ·
`VerificationReport.failure` · `VerificationReport.skill_resolution`

M6 reads all ten without complaint, because it does not validate the report.

**Recommended:** generate `../schemas/` from the models at version `2.0.0` and retire
the extension list — M6 reads the same folder, so one change reaches both.

### 2. Non-competitive-programming achievements

On the professional CV, six real claims — patents, 38K GitHub stars, published books —
were extracted and correctly refused as unattributable. "38K GitHub stars" is
checkable from the API. **A new check, not a fix.**

---

## Risks

| | Risk | Severity | Why |
|---|---|---|---|
| 1 | **No git remote** | 🔴 high | 82 commits, now all three modules and the web layer, exist on one laptop |
| 2 | **Personal data in git history** | 🔴 high | two CVs, the design PDF's worked example, and cached API responses — blocks any public push. `.cache/` is no longer tracked (`c663d73`), but its old files stay in history |
| 3 | **Extraction accuracy unmeasured** | 🟠 medium | no gold set |
| 4 | **One document measured since October** | 🟠 medium | every new document so far has found a real bug |
| 5 | **Scraper drift** | 🟡 low | a CodeChef redesign turns P5 into a gap, never a false finding; the fix is the scraper |

**Recommended order:** a private remote first; a history rewrite only if the repository
is ever made public.

---

## Next, ranked

| | Work | Effort | Unblocks |
|---|---|---|---|
| 1 | Private git remote | 10 min | removes the largest risk |
| 2 | Re-run the two September documents | 15 min | a measurement table from one version of the system |
| 3 | Decide the contract (§ Decisions 1) | a conversation | retires the extension list |
| 4 | **Gold set** — 10–20 hand-labelled CVs | days | extraction metrics for the thesis |
| 5 | Honest-variation tests in `cvv evaluate` | a day | the seven fairness bugs were invisible to a harness that only corrupts |

Known and left alone for a college project: SSRF on the probe, `document_url` and
webhooks; no retention or delete; Postgres rows that can stay `pending`; webhooks that
always say "completed". The narrative also prints each benign reading twice — once in
the model's sentence, once by Python.
