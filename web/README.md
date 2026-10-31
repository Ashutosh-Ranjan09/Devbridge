# DevBridge — web

The website: candidates upload a CV, see their skill profile and take assessments;
recruiters confirm a job's skills, read the evidence and chat with applicants (asking for
documents they upload there); admins see the system's state. Next.js 16 with its own
SQLite database for accounts. Everything about CVs, skills, assessments and chats comes
from the four Python modules over HTTP.

```bash
npm install
cp .env.example .env
npm run db:migrate
npm run dev        # http://localhost:3000
npm run check      # types, lint, tests
```

Read [`CLAUDE.md`](CLAUDE.md) for the layout, how to run the modules beside it, and
the guardrails.
