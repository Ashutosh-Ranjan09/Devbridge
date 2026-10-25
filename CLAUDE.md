# DevBridge — M5 and M6

Two modules, one repository. Each has its own CLAUDE.md with its guardrails; read the
one for the module you are working in.

| | Folder | Tooling |
|---|---|---|
| M5 · CV verification | `cv-verification/` — see its `CLAUDE.md` | uv · pytest · ruff · `mypy --strict`; run commands from inside the folder (`.env`, `.cache/` are relative to it) |
| M6 · skill graph | `skill-graph/` — see its `CLAUDE.md` | stdlib + pyyaml + jsonschema · `make test` / `make all`; `PYTHONPATH=packages` |
| The contract | `schemas/` | read by both; one copy, so a change reaches both |
| The skill list | `schemas/skills/` | `ontology.yaml` (skills, tiers, links) and `aliases.yaml`; M5 resolves names against it, M6 scores by it |
| Design pages | `docs/` | shared; M6-only pages are in `skill-graph/docs/` |

## The seam

M5 writes the contract's `VerificationReport` (`cvv verify --save DIR` →
`verification-report.json`; `GET /v1/verifications/{id}` returns the same object). M6
reads that and nothing else: its projector (6.0) turns it into evidence events. M5
does not project events — deciding what evidence is worth for a skill is M6's job.

M5 does say which listed skill each name means: `skill_resolution` in the report, from
rules, a cache, then a closed-choice model call (one id from `schemas/skills/`, or none).
That is the only model use near the seam. M6 reads the answers and contains no model.

A change to either side of the seam is proven by running a real report through both,
not by either module's tests alone. The first real handoff broke at seven points —
three in M5, four in M6 — and both test suites passed every one.

- M5's report carries ten fields the schema does not define (listed in
  `cv-verification/tests/test_contract.py`). M6 tolerates them because it does not
  validate the report it reads.
- Consent handling was removed from both modules as out of scope for this project.
  `consent_ref` and `consent_scope` survive only as unused contract fields.
- Neither module may publish an overall score, in any form.
