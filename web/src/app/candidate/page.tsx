import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { requireRole } from "@/lib/auth";
import { db } from "@/lib/db";

export default function CandidateHome() {
  return (
    <Page title="Your profile">
      <Suspense fallback={<Loading />}>
        <Profile />
      </Suspense>
    </Page>
  );
}

async function Profile() {
  const user = await requireRole("CANDIDATE");
  const candidate = await db.candidate.findUniqueOrThrow({ where: { userId: user.id } });
  return (
    <Card>
      <p>Signed in as {user.name} ({user.email}).</p>
      <p className="mt-2 text-sm text-muted">
        The modules know you only as <code>{candidate.subjectRef}</code>, never by name or email.
      </p>
      <p className="mt-4 text-sm text-muted">Next: upload a CV, your skill profile, jobs and assessments.</p>
    </Card>
  );
}
