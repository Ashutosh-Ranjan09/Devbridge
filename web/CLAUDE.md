# DevBridge — web

The pages candidates, recruiters and admins use, and the server side behind them. The
browser talks only to this app; this app talks to M5, M6 and assessment over HTTP.

**Next.js 16 is not the Next.js in your training data.** Read the guide in
`node_modules/next/dist/docs/` before writing Next code (`AGENTS.md`, written by
`next dev`, says the same). Cache Components is on: anything that reads the session
renders behind `<Suspense>`.

| | |
|---|---|
| Stack | Next.js 16 (App Router, Cache Components) · React 19 · TypeScript · Tailwind 4 · Prisma 7 + SQLite (better-sqlite3 adapter) · Zod 4 · bcryptjs · react-markdown · Vitest |
| Data | `.data/web.db` (gitignored): users, sessions, organisations, and links to module ids |
| Checks | `npm run check` — `next typegen`, `tsc`, ESLint, Vitest |

```
npm install                       # also generates the Prisma client (src/generated/, gitignored)
cp .env.example .env              # module URLs and keys
npm run db:migrate                # create or update .data/web.db
npm run create-admin -- EMAIL "NAME"
npm run dev                       # http://localhost:3000
npm run check · npm run build
```

All four at once, with one key per module shared through the environment:
`../scripts/dev.sh` (or `../scripts/dev.sh prod`). Or each module in its own terminal
(any that is down shows as such on `/admin`):

```
cd cv-verification && uv run cvv serve                       # :8080, prints its key
cd skill-graph && PYTHONPATH=packages python3 -c 'from m6 import M6; from m6.api import serve; serve(M6("evidence.db"), port=8300).serve_forever()'
cd assessment && uv run assess serve                         # :8070, prints its key
```

## Layout

```
src/proxy.ts            optimistic redirect to /login when there is no session cookie
src/lib/db.ts           the Prisma client
src/lib/session.ts      create · read · delete a database session
src/lib/auth.ts         currentUser() and requireRole(): the only cookie → person path
src/lib/password.ts     bcrypt, cost 12
src/lib/definitions.ts  Zod schemas for every form
src/lib/services.ts     call() to M5 · M6 · assessment (JSON or multipart); health()
src/lib/types.ts        the fields of each module's answers that pages read
src/lib/candidate.ts    requireCandidate(); myVerification() / myAssessment(): theirs, or 404
src/lib/recruiter.ts    requireRecruiter(); myJob() / myApplication(): their organisation's, or 404
src/lib/review.ts       an M5 report's lines as keys; marksFor(): the newest admin mark on each
src/lib/sync.ts         reports and results to M6, unchanged; sentToM6At once M6 accepts
src/app/(auth)/         login, signup, and their server actions
src/app/candidate/      overview · cv (upload, report) · skills (profile, explain) ·
                        assessments (practice, task, editor, result) · jobs (apply, decisions) · actions.ts
src/app/recruiter/      jobs · jobs/new · jobs/[id] (skills table, confirm, open, applicants) ·
                        jobs/[id]/applicants/[appId] (evidence, assessment, decision) · actions.ts
src/app/admin/          system (modules, counts) · accounts · candidates (each one's CV reports,
                        every line markable) · catalogue (M5's checks, the tasks) ·
                        quarantine (skills M6 holds because the list lacks them) · actions.ts
src/app/not-found.tsx   one page for "does not exist" and "is not yours"
src/app/error.tsx       an unexpected failure: a retry button and the server log's digest
src/components/         ui · report (M5's buckets, in M5's order) · interval · markdown · musts
                        (an applicant's must-haves, as M6's shortlist answered) · action-button ·
                        candidate, recruiter, admin (the client components: forms, refresh, countdown, editor)
prisma/schema.prisma    the tables; migrations in prisma/migrations/
tests/                  Vitest: actions against a temporary database; service calls
```

## Guardrails — do not weaken these

1. **The browser never reaches a module.** URLs and keys live in `lib/services.ts`,
   which is `server-only`; never a `NEXT_PUBLIC_` variable.
2. **No business logic here.** What evidence is worth, whether a must-have is met, what
   a test result means: a module says it, this app shows it. If a page needs a number
   no module returns, the module gains an endpoint.
3. **Nothing is scored or ranked.** No overall score on any page. Lists of people are
   ordered by name or date, never by a skill. A decision needs a person and a written
   reason, and is stored with both.
4. **The modules see only `subject_ref`.** Never send a name or an email to M5, M6 or
   assessment. Only `Candidate` maps a subject to a person.
5. **Every page and every server action checks the role itself** with `requireRole`.
   The proxy only saves a round trip; a server action can be called without the page.
6. **This database holds who and which, never what.** No copy of a report, a skill
   interval, a job's skills or a result: fetch it from the module that owns it.
7. **A candidate sees the candidate view.** `view=full` on an assessment result
   (failure details, which quote the hidden tests) is for the recruiters of that job
   and admins only.
8. **Passwords and sessions:** bcrypt cost 12; one message for a wrong email and a wrong
   password, with a comparison either way; the session table stores the token's
   SHA-256, never the token; the cookie is httpOnly, SameSite=Lax, Secure in production.
   Admins are made with `create-admin`, never by signing up.
9. **Text from a module or a CV is shown as text.** React escapes it; Markdown (task
   stories and requirements) only through react-markdown, which renders no raw HTML —
   never add `rehype-raw`, never `dangerouslySetInnerHTML`. A CV can carry anything.
10. **Another user's id is a 404, the same as an id that does not exist** (`myVerification`,
    `myAssessment`), so ids cannot be probed. Load a row through its owner, never by id alone.
11. **Evidence reaches M6 unchanged and at least once.** `lib/sync.ts` forwards a report
    or a result exactly as the module returned it; M6's ingest is idempotent, so a retry
    is safe, and `sentToM6At` is set only once M6 has accepted it. A module being down
    delays the evidence (`after()`, retried from the skills page), never a page.
12. **A recruiter reaches a candidate only through an application** to their organisation's
    job (`myApplication`). Applicants are listed by name; whether someone clears a bar is
    M6's `clears`, shown as it came; filtering to those who clear every bar is a link the
    recruiter clicks, never the default. A decision needs an outcome and a reason, is made
    once, records who made it, and the candidate reads it.
13. **A refused action returns what was typed** (`values`), and the form uses it as its
    defaults: React 19 resets a form after its action runs, so a field with nothing passed
    back comes back empty — a candidate's code after a 503, a job's other edits after one
    bad bar. A `<select>` also needs a `key` from that value; React applies its default
    only when it mounts.
14. **An admin's mark sits beside M5's line, never in place of it.** `ItemReview` holds
    a person's verdict on one line of a report (verified or unverified, a note of at
    least 10 characters saying what they checked, who, when), like a `Decision`: a
    person's judgement, not a copy of the report. M5's buckets and wording are unchanged
    and the mark is labelled as an admin's; the candidate and recruiters see "an admin",
    the admin area the name. Rows are never updated: marking again adds one, and the
    newest is current. The action checks the key against the report from M5, so only a
    real line can be marked. A mark does not reach M6 and does not change any skill.

## Known limits, stated

- No rate limit on login, no email verification, no password reset.
- `create-admin` shows the password as it is typed (it stays out of shell history).
- A session is not rotated on use; it lasts seven days or until logout.
- A running verification is polled every 4 s by re-rendering the page.
- M5 without `CVV_DATABASE_URL` keeps reports in memory: after a restart, a report page
  says M5 does not know the verification.
- Every session read calls `connection()`: Next 16 prefetches linked pages by
  prerendering them, and a session (its expiry check reads the clock) must not be
  decided there. Prefetches stop at the static shell.
- Blanking a bar that is already set keeps the old one: `jd.edit` reads "none" as "unchanged".
  Drop the skill and add it again to remove a bar.
- The recruiter sees a candidate's latest CV report only.
- A line is keyed by its place in its bucket (findings by their id). That holds because
  M5 never changes a stored report; a re-check is a new verification with its own marks.
- An admin's mark is not evidence for M6: making it count needs a new event kind in the
  contract and M6 deciding what a human check is worth (with W2's queue).
- Not built: adding context to a "needs
  context" finding (M5's attestation is out of scope); the CLI's "also checked, nothing
  raised" lines, which M5 computes for the CLI and does not put in the report.
