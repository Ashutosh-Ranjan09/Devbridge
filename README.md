# DevBridge — verified skills from a CV

Two modules of the DevBridge platform, in one repository. A B.Tech project.

| | Module | What it does |
|---|---|---|
| [`cv-verification/`](cv-verification/) | **M5 · CV Verification Engine** | checks a CV against the systems it names — GitHub, Codeforces, LeetCode, CodeChef, live deployments — and reports evidence, with provenance. No score, no verdict |
| [`skill-graph/`](skill-graph/) | **M6 · Verified Skill Graph** | turns that report into a per-skill estimate of ability, as an interval, that decays as evidence ages and can be explained event by event. No overall score |
| [`schemas/`](schemas/) | the contract | `verification-report.schema.json` (M5's output, M6's input), `evidence-event.schema.json` (M6's events), reference payloads, and `skills/` — the one skill list both modules use |
| [`docs/`](docs/) | design pages | the check catalogue, the integration spec, the CV-to-skill-graph shapes, the platform plan |

Neither module produces a number that summarises a person, and both say what they
could not check.

## From a CV to a skill graph

```
CV ──M5──▶ verification-report.json ──M6──▶ evidence events ──▶ skill intervals
           (schemas/verification-report)     (schemas/evidence-event)
```

```bash
cd cv-verification
uv sync
uv run cvv verify docs/CV-SDE-AR.pdf --save out/      # writes out/verification-report.json

cd ../skill-graph
PYTHONPATH=packages python3 -m m6_projection ../cv-verification/out/verification-report.json --out batch.json
PYTHONPATH=packages python3 -m m6_ingestor ingest batch.json --db evidence.db
PYTHONPATH=packages python3 -m m6_query skills --db evidence.db
```

M5 reports what the evidence says, and which listed skill each name means; M6 decides
what it is worth for each skill. That line is deliberate: M5 once projected its own
events and M6 quarantined every one.

## Running each module

| | Setup | Tests |
|---|---|---|
| M5 | Python 3.12, [uv](https://docs.astral.sh/uv/), and Ollama or the Claude Code wrapper — see [`cv-verification/README.md`](cv-verification/README.md) | `uv run pytest` — 574 |
| M6 | Python 3.12 with `pyyaml` and `jsonschema`, nothing else — see [`skill-graph/CLAUDE.md`](skill-graph/CLAUDE.md) | `make test` — 572, or `make all` for every gate |

## Personal data

`cv-verification/docs/` holds real CVs, and a verification report names a real person.
Reports, caches (`cv-verification/.cache/`), run output (`cv-verification/out/`) and
M6's `evidence.db` stay on this machine; the last three are ignored by git.
