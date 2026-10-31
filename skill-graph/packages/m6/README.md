# m6 — module 6, composed

**Status: complete (v1.0.0).** All six submodules behind one interface.

```python
from m6 import M6
with M6("evidence.db") as m6:
    m6.ingest_report(report)                       # 6.0 then 6.2
    m6.profile("subj_7a3f9e21", date(2026, 8, 24)) # 6.3, 6.4 and 6.5
```

```
make demo         # the end-to-end walkthrough
make demo-http    # ...plus every HTTP endpoint, live
make test         # 603 tests across every package
```

## The wiring

```
report --6.0--> events --6.2--> log --6.3--> states --6.4--> answers
                                 |                             ^
                                6.1 ontology ------------------+
                                 |
                                6.5 reads the log and the states, writes nothing
```

One-way, with one exception that is deliberate: 6.5 reads what 6.3 produced but
nothing reads 6.5.

| submodule | package | |
|---|---|---|
| 6.0 | `m6_projection` | verified artefacts → evidence events |
| 6.1 | `m6_ontology` | skills, tiers, edges; validates `../schemas/skills/ontology.yaml` |
| 6.2 | `m6_ingestor` | validation, idempotency, append-only log |
| 6.3 | `m6_scoring` | observation model, Kalman, decay, propagation |
| 6.4 | `m6_query` | intervals, explain, tiered search |
| 6.5 | `m6_integrity` | findings about the shape of the evidence |

## HTTP

`POST /evidence/report` takes a raw M5 report and runs 6.0 then 6.2, so a caller
never has to know the projection exists. Everything else is a GET.

In deployment 6.2 and 6.4 are separate services on separate ports — writing and
reading scale differently. `m6.api` composes them for the demo and for anyone who
wants module 6 as one process; the query routes are **reused verbatim** from
`m6_query.api` rather than reimplemented, so the two surfaces cannot drift apart.

## What the facade is not

It is a convenience, not a second implementation — `test_the_facade_and_the_submodules_agree`
asserts that calling through `M6` gives byte-identical results to calling the
submodules directly. If that test ever fails, the facade has started making
decisions of its own, which is the thing to prevent.

`m6.versions()` returns every package and contract version behind an answer. A
score without those cannot be reproduced or disputed.

## Tests — 36 here, 584 across the repo

`test_composition.py` tests the wiring: that guarantees survive composition, that
two subjects stay separate, that a quarantined skill is absent from the graph
*and* present in the integrity report. `test_http.py` runs the combined server
over real sockets, including eight concurrent readers against one writer.
`test_demo.py` treats the walkthrough as a deliverable — it validates the demo
input against M5's own schema, runs the script end to end, and checks the demo
README's numbers still match what the code produces.
