# DevBridge — web

The website: candidates upload a CV, see their skill profile and take assessments;
recruiters confirm a job's skills and read the evidence; admins see the system's state.
Next.js 16 with its own SQLite database for accounts. Everything about CVs, skills and
assessments comes from the three Python modules over HTTP.

```bash
npm install
cp .env.example .env
npm run db:migrate
npm run dev        # http://localhost:3000
npm run check      # types, lint, tests
```

Read [`CLAUDE.md`](CLAUDE.md) for the layout, how to run the modules beside it, and
the guardrails.
