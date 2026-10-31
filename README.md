# DevBridge — verified skills from a CV

Three modules of the DevBridge platform and the website in front of them, in one
repository. A B.Tech project.

| | Module | What it does |
|---|---|---|
| [`cv-verification/`](cv-verification/) | **M5 · CV Verification Engine** | checks a CV against the systems it names — GitHub, Codeforces, LeetCode, CodeChef, live deployments — and reports evidence, with provenance. No score, no verdict |
| [`skill-graph/`](skill-graph/) | **M6 · Verified Skill Graph** | turns that report into a per-skill estimate of ability, as an interval, that decays as evidence ages and can be explained event by event. No overall score |
| [`assessment/`](assessment/) | **Assessment** | turns a job description into confirmed skill requirements, shortlists candidates through the skill graph, and gives each a unique, equally hard coding task, run in a sandbox and scored by hidden tests. The result goes back into the skill graph |
| [`web/`](web/) | **Web** | the website: candidates, recruiters and admins sign in; it calls the three modules over HTTP and keeps only accounts and links to their ids |
| [`schemas/`](schemas/) | the contract | `verification-report.schema.json` (M5's output, M6's input), `evidence-event.schema.json` (M6's events), reference payloads, `skills/` — the one skill list every module uses — and `job-requirements.schema.json` |
| [`docs/`](docs/) | design pages | the check catalogue, the integration spec, the CV-to-skill-graph shapes, the platform plan |

No module produces a number that summarises a person, and each says what it could not
check.

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

## The website

```bash
cp web/.env.example web/.env         # once; then (cd web && npm install)
scripts/dev.sh                       # M5 :8080 · M6 :8300 · assessment :8070 · web :3000
scripts/dev.sh prod                  # the same with a production build of the web
(cd web && npm run create-admin -- EMAIL "NAME")   # an admin, for /admin
```

One command starts all four with one key per module per run, passed through the
environment and never printed; logs go to `.run/`, and Ctrl-C stops everything.
Candidates check a CV (with their platform usernames and a note, both optional), see
their skills and take assessments (Start when ready, run the visible examples, up to
three submissions, the last counts); recruiters confirm a job's skills and the tasks
every applicant gets, send them with a start-by date, read each applicant's evidence and
every attempt, and decide, with a reason the candidate reads; admins see the
system's state, mark any line of a candidate's CV report verified or unverified with a
note, and make one-time password reset links. Everyone can change their password on
`/account`; five wrong logins lock an email for 15 minutes. See
[`web/CLAUDE.md`](web/CLAUDE.md).

## From a job description to a task

```bash
cd assessment
uv run assess jd new jd.txt && uv run assess jd confirm JOB --by me
uv run assess jd export JOB --out requirements.json
cd ../skill-graph && PYTHONPATH=packages python3 -m m6_query shortlist --db evidence.db --requirements ../assessment/requirements.json
cd ../assessment && uv run assess start --job JOB --candidate subject:…   # then: assess submit, assess events
```

## Running each module

| | Setup | Tests |
|---|---|---|
| M5 | Python 3.12, [uv](https://docs.astral.sh/uv/), and Ollama or the Claude Code wrapper — see [`cv-verification/README.md`](cv-verification/README.md) | `uv run pytest` — 630 |
| M6 | Python 3.12 with `pyyaml` and `jsonschema`, nothing else — see [`skill-graph/CLAUDE.md`](skill-graph/CLAUDE.md) | `make test` — 595, or `make all` for every gate |
| Assessment | Python 3.12, uv, Docker — see [`assessment/README.md`](assessment/README.md) | `uv run pytest` — 124; `-m docker` 12, `-m slow` 1 more |
| Web | Node 24, npm — see [`web/CLAUDE.md`](web/CLAUDE.md) | `npm run check` — 82 |

## Personal data

`cv-verification/docs/` holds real CVs, and a verification report names a real person.
Reports, caches (`cv-verification/.cache/`), run output (`cv-verification/out/`) and
M6's `evidence.db`, the assessment module's `.data/` (jobs, sessions, submitted code) and
the web layer's `.data/` (accounts, password hashes) stay on this machine; all but the CVs are ignored by git.
