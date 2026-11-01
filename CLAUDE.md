# DevBridge — M5, M6, assessment, chat and web

Four modules and a web layer, one repository. Each has its own CLAUDE.md with its
guardrails; read the one for the folder you are working in.

| | Folder | Tooling |
|---|---|---|
| M5 · CV verification | `cv-verification/` — see its `CLAUDE.md` | uv · pytest · ruff · `mypy --strict`; run commands from inside the folder (`.env`, `.cache/` are relative to it) |
| M6 · skill graph | `skill-graph/` — see its `CLAUDE.md` | stdlib + pyyaml + jsonschema · `make test` / `make all`; `PYTHONPATH=packages` |
| Assessment | `assessment/` — see its `CLAUDE.md` | uv · pytest · ruff · `mypy --strict` · Docker for the sandbox; settings from `assessment/.env` wherever you run it |
| Chat | `chat/` — see its `CLAUDE.md` | uv · pytest · ruff · `mypy --strict`; settings and the encryption key from `chat/.env`. Recruiter ↔ candidate, one thread per application, encrypted at rest |
| Web | `web/` — see its `CLAUDE.md`; `scripts/dev.sh` runs all five | Next.js 16 · TypeScript · Prisma 7 + SQLite · Vitest · `npm run check`; the only part a browser talks to, and it reaches the modules over HTTP |
| The contract | `schemas/` | read by every module; one copy, so a change reaches all of them |
| The skill list | `schemas/skills/` | `ontology.yaml` (skills, tiers, links) and `aliases.yaml`; M5 resolves names against it, M6 scores by it, assessment tags patterns and JD skills with it |
| Job requirements | `schemas/job-requirements.schema.json` | a confirmed job's must-haves (with bars) and nice-to-haves; assessment writes it, M6's shortlist reads it |
| Design pages | `docs/` | shared; M6-only pages are in `skill-graph/docs/` |

## The seam

One CV per developer: of a developer's reports, M6 counts only the one M5 checked last;
every older report's evidence is skipped (kept in the log, never deleted), and assessment
results always count. A new CV therefore replaces the old one in every skill.

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

- M5's report carries eleven fields the schema does not define (listed in
  `cv-verification/tests/test_contract.py`). M6 tolerates them because it does not
  validate the report it reads.
- Consent handling was removed from every module as out of scope for this project.
  `consent_ref` and `consent_scope` survive only as unused contract fields.

## The second seam: assessment

```
JD ─▶ assessment: skills proposed (model, grounded in the JD) ─▶ a person confirms
   ─▶ requirements.json ─▶ M6 shortlist (must-haves filter; never ranked)
   ─▶ assessment: the job's chosen tasks, each a unique, equally hard variant per candidate
   ─▶ Docker ─▶ tests passed (up to three attempts; the last counts)
   ─▶ assessment_result batch ─▶ M6 ingest (priced by m6-parameters.yaml)
```

The assessment module imports nothing from cvv or M6; it meets both through
`schemas/`. It emits facts (level, tests passed, total); M6 decides what they are worth.
Its model only chooses from lists and writes stories; code renders every requirement
and every hidden test, and a pattern is used only after its tests are proven right in
every combination.

- No module may publish an overall score, rank by a combination of skills, or filter
  candidates on the system's own judgement. A person confirms a job's requirements,
  and a person reads the results.

  One exception, decided by the project owner: a job's assessment is scored the way an
  online test is (`GET /v1/jobs/{id}/results`). Each task is ranked on its own (hidden
  tests passed, then time), and the assessment has a total: each task worth 100 points,
  summed over that job's tasks, then less time. That total is the score of one test and
  nothing else; no skill interval, CV report or other job is ever added in, M6 never
  sees it, nobody is filtered by it, and a person still picks and decides.

  A second, also the owner's: M6's shortlist gives each applicant a **job match** — that
  job's skills averaged from M6's intervals, a must-have counting 2 and a nice-to-have 1
  (`m6-parameters.yaml` `job_match`), a skill with no evidence at the prior (0.25,
  0.08–0.55), as a range with how many skills have direct evidence. It belongs to one
  applicant and one confirmed job, never to the person; it filters nobody (the bars do),
  and only that job's recruiters see it. M6 answers alphabetically; the web lists by name
  by default, and a recruiter may sort that job's applicants by the match's middle value.

## Chat

`chat/` holds the conversations between a candidate and the recruiters of a company they
applied to: one thread per application, opened only by a recruiter, so no candidate can
write to a company first. It meets the rest only through the web, which checks who is on
a thread and relays the live stream; it knows people by the web's user ids, never by name
or email, and imports nothing from the other modules. Messages are encrypted at rest
(AES-256-GCM, key in `chat/.env`) and never edited or deleted — encrypted at rest, not
end to end, and every description must say which.
