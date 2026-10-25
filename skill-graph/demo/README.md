# demo — module 6, end to end

A hand-runnable walkthrough. Not a test: this exists to be **read** and run,
so you can see what each submodule decides on one realistic input.

```
python3 demo/run_demo.py              # the whole walkthrough
python3 demo/run_demo.py --http       # also exercise every HTTP endpoint
python3 demo/run_demo.py --step 5     # just the explain step
python3 demo/run_demo.py --skill cpp  # explain a different skill
make demo                             # the same thing
```

Every number printed is computed live. Nothing is hard-coded.

## The input

`input/verification-report-extensive.json` — a complete M5 `VerificationReport`,
**validated against `../schemas/verification-report.schema.json`**. It is
deliberately messier than the golden example, so the walkthrough has something to
show at every stage:

| | |
|---|---|
| 30 claims | across all nine kinds, including two certifications and a `declaration_marker` that disclaims CGPA and coursework |
| 7 repositories | four real, plus a fork, a README-only shell, and one that is not owned |
| 2 platforms | Codeforces over the official API, CodeChef **scraped** — different reliability |
| 2 deployments | one live, one returning 502 |
| 2 credentials | one confirmed by the issuer, one where the issuer was unreachable |
| 2 gaps | a LeetCode handle that was never given, a private repository |
| 4 discrepancies | including a Rust claim with no Rust anywhere |

Three things in it are there to trip specific machinery: `haskell` and a
`Jupyter Notebook` language are **not in the ontology** (quarantine), the CV is
dated six weeks before verification (CV claims must not get the fresh date), and
the "900+ problems across three platforms" claim carries M5's
`aggregate_across_sources` flag and an open bound (two named discounts).

## The steps

| | |
|---|---|
| **1** | The input — what M5 hands over |
| **2** | **6.0** projection: 30 claims and 7 repos → 21 events + 7 recorded suppressions |
| **3** | **6.2** ingestion: quarantine, replay is a no-op, consent refused again, the log refuses an UPDATE |
| **4** | **6.3** scoring: the graph, then the same graph two years later with no new evidence |
| **5** | **6.4** explain: every contributing event with its weight, and what was *not* counted |
| **6** | **6.4** search: tiers, and the difference between "clears the bar" and "reaches it" |
| **7** | **6.5** integrity: 12 findings, each with its innocent explanation |
| **8** | The guarantees: no overall score, integrity changes nothing, every contract version named |
| **9** | Every HTTP endpoint, live on an ephemeral port (`--http`) |

## The output

`output/` is regenerated on every run:

```
01-projected-batch.json   what 6.0 emitted, and what it refused to emit
02-ingest-receipt.json    accepted / duplicate / quarantined
03-skill-graph.json       19 skills as intervals
04-explain.json           one skill, fully decomposed
05-integrity.json         12 findings
```

## What to look for

**Step 2** — the CodeChef rating comes in at reliability 0.63, not 0.90: it was
scraped rather than read from an API, and the discount is named on the event.
The CV claims are dated `2026-07-12`, the document's own date, not the
verification date.

**Step 3** — `haskell` and `jupyter_notebook` are quarantined. The events are
*stored*, not dropped; they will count the moment the ontology carries those
skills. Replaying the whole report accepts nothing and the log stays at 21.

**Step 4** — the published score is the **lower bound**, and every row carries
its interval. Four skills are marked inferred with zero evidence — `c` from
`cpp`, `sql` from `postgresql`. Two years on, every interval is wider.

**Step 7** — twelve findings, all `notice`, none `attention`. This candidate's
GitHub account is OAuth-verified, so the ownership check stays quiet; contrast
with the golden report, where it fires.

**Step 8** — `GET /developers/{ref}/score` returns 400 with a reason, and the
skill graph is byte-identical before and after 6.5 runs.
