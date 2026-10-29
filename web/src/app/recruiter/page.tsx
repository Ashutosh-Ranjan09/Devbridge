import Link from "next/link";
import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { db } from "@/lib/db";
import { requireRecruiter } from "@/lib/recruiter";
import { call } from "@/lib/services";
import type { Job } from "@/lib/types";

export default function RecruiterHome() {
  return (
    <Page title="Jobs">
      <Suspense fallback={<Loading />}>
        <Jobs />
      </Suspense>
    </Page>
  );
}

async function Jobs() {
  const me = await requireRecruiter();
  const jobs = await db.job.findMany({
    where: { orgId: { in: me.orgIds } },
    include: { org: true, _count: { select: { applications: true } } },
    orderBy: { createdAt: "desc" },
  });
  const states = await Promise.all(
    jobs.map((j) => call<Job>("assess", `/v1/jobs/${encodeURIComponent(j.id)}`).then((x) => x.status, () => null)),
  );
  return (
    <Card>
      <p className="mb-3 text-sm text-muted">
        Hiring for {me.orgs.map((o) => `${o.name} (${o.kind === "CLIENT" ? "freelance client" : "company"})`).join(", ")}.
      </p>
      {jobs.length === 0 ? (
        <p>No jobs yet. <Link href="/recruiter/jobs/new" className="text-accent underline">Start one from a job description</Link>.</p>
      ) : (
        <ul className="space-y-2">
          {jobs.map((j, i) => (
            <li key={j.id} className="flex flex-wrap gap-x-3">
              <Link href={`/recruiter/jobs/${j.id}`} className="text-accent underline">{j.title}</Link>
              <span className="text-sm text-muted">{states[i] === "confirmed" ? "skills confirmed" : states[i] === "proposed" ? "skills to review" : "status unavailable"}</span>
              <span className="text-sm text-muted">{j.open ? "open" : "not listed"}</span>
              <span className="text-sm text-muted">{j._count.applications} applicant(s)</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
