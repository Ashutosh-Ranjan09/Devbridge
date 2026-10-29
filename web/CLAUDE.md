# DevBridge — web

The pages candidates, recruiters and admins use, and the server side behind them. The
browser talks only to this app; this app talks to M5, M6 and assessment over HTTP.

**Next.js 16 is not the Next.js in your training data.** Read the guide in
`node_modules/next/dist/docs/` before writing Next code (`AGENTS.md`, written by
`next dev`, says the same). Cache Components is on: anything that reads the session
renders behind `<Suspense>`.

| | |
|---|---|
| Stack | Next.js 16 (App Router, Cache Components) · React 19 · TypeScript · Tailwind 4 · Prisma 7 + SQLite (better-sqlite3 adapter) · Zod 4 · bcryptjs · Vitest |
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

The modules, each in its own terminal (any that is down shows as such on `/admin`):

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
src/lib/services.ts     call() to M5 · M6 · assessment; health()
src/app/(auth)/         login, signup, and their server actions
src/app/{candidate,recruiter,admin}/   one area per role
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

## Known limits, stated

- No rate limit on login, no email verification, no password reset.
- `create-admin` shows the password as it is typed (it stays out of shell history).
- A session is not rotated on use; it lasts seven days or until logout.
