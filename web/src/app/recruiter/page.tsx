import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { requireRole } from "@/lib/auth";
import { db } from "@/lib/db";

export default function RecruiterHome() {
  return (
    <Page title="Hiring">
      <Suspense fallback={<Loading />}>
        <Organisations />
      </Suspense>
    </Page>
  );
}

async function Organisations() {
  const user = await requireRole("RECRUITER");
  const memberships = await db.membership.findMany({ where: { userId: user.id }, include: { org: true } });
  return (
    <Card>
      <p>Signed in as {user.name}, hiring for:</p>
      <ul className="mt-2 list-disc pl-6">
        {memberships.map(({ org }) => (
          <li key={org.id}>
            {org.name} <span className="text-sm text-muted">({org.kind === "CLIENT" ? "freelance client" : "company"})</span>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-sm text-muted">Next: jobs, confirmed skills, applicants and assessments.</p>
    </Card>
  );
}
