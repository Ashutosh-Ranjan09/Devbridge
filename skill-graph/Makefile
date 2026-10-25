PY := PYTHONPATH=packages python3
DB := evidence.db
AS_OF ?= 2026-08-24
SKILL ?= typescript

.PHONY: help test demo demo-http ontology project batch ingest score why find \
        integrity profile serve api recover sweep verify all clean

help:            ## list targets
	@grep -hE '^[a-z][a-z-]*:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

test:            ## every suite, no pytest required; `make test FILTER=x` narrows
	$(PY) tests/run.py $(FILTER)

# ── the demonstration ────────────────────────────────────────────────────────
demo:            ## end-to-end walkthrough on the extensive example report
	$(PY) demo/run_demo.py
demo-http:       ## the walkthrough plus every HTTP endpoint, live
	$(PY) demo/run_demo.py --http

# ── one submodule at a time, on the golden report ────────────────────────────
ontology:        ## 6.1 — check the seed graph, then show it
	$(PY) -m m6_ontology check
	$(PY) -m m6_ontology skills
	$(PY) -m m6_ontology edges
project:         ## 6.0 — project the golden report to batch.json
	$(PY) -m m6_projection ../schemas/examples/report-full.json --out batch.json
batch:           ## 6.0 — project both example reports
	$(PY) -m m6_projection ../schemas/examples/report-full.json --out batch-full.json
	$(PY) -m m6_projection ../schemas/examples/report-degraded.json --out batch-degraded.json
ingest: project  ## 6.2 — push the golden batch into the log
	$(PY) -m m6_ingestor ingest batch.json --db $(DB)
score: ingest    ## 6.3 — score the whole graph from the log
	$(PY) -m m6_scoring score --db $(DB) --as-of $(AS_OF)
query: ingest    ## 6.4 — the graph as the API presents it
	$(PY) -m m6_query skills --db $(DB) --as-of $(AS_OF)
why: ingest      ## 6.4 — the explain response: make why SKILL=cpp
	$(PY) -m m6_query explain --db $(DB) --skill $(SKILL) --as-of $(AS_OF)
find: ingest     ## 6.4 — search: make find SKILL=typescript MIN=0.3
	$(PY) -m m6_query search --db $(DB) --skill $(SKILL) --min $(or $(MIN),0.0) --as-of $(AS_OF)
integrity:       ## 6.5 — integrity findings for the golden subject
	$(PY) demo/run_demo.py --input ../schemas/examples/report-full.json --step 7
profile:         ## the whole layer in one call: skills + integrity
	$(PY) demo/run_demo.py --input ../schemas/examples/report-full.json --step 8

# ── servers ──────────────────────────────────────────────────────────────────
serve:           ## 6.2 — the ingestor alone on :8100
	$(PY) -m m6_ingestor serve --db $(DB) --port 8100
api:             ## 6.4 — the query api alone on :8200
	$(PY) -m m6_query serve --db $(DB) --port 8200

# ── checks ───────────────────────────────────────────────────────────────────
recover:         ## 6.3 — the gate: can the filter recover a known ability?
	$(PY) -m m6_scoring recover
sweep:           ## 6.3 — every parameter the sensitivity sweep may vary
	$(PY) -m m6_scoring sweep
verify:          ## re-check the scoring model against the worked example
	$(PY) contracts/reference/verify_worked_example.py

all: test ontology verify recover demo  ## everything, in order

clean:
	find . -name __pycache__ -prune -exec rm -rf {} + ; rm -f batch*.json $(DB)
