import { Suspense } from "react";

import { NewJobForm } from "@/components/recruiter";
import { Card, Loading, Page } from "@/components/ui";
import { requireRecruiter } from "@/lib/recruiter";

export default function NewJobPage() {
  return (
    <Page title="New job">
      <Card>
        <p className="mb-4 text-sm text-muted">
          Paste the job description. Skills are proposed from it, each with the words it was found in, and
          nothing is used until you have reviewed and confirmed them.
        </p>
        <Suspense fallback={<Loading />}>
          <Form />
        </Suspense>
      </Card>
    </Page>
  );
}

async function Form() {
  const me = await requireRecruiter();
  return <NewJobForm orgs={me.orgs.map((o) => ({ id: o.id, name: o.name }))} />;
}
