import { after } from "next/server";
import { Suspense } from "react";

import { Refresh } from "@/components/candidate";
import { ReportView } from "@/components/report";
import { Card, Loading, Page } from "@/components/ui";
import { myVerification, requireCandidate } from "@/lib/candidate";
import { call, ServiceError } from "@/lib/services";
import { marksFor } from "@/lib/review";
import { forwardReport } from "@/lib/sync";
import type { Report, Running } from "@/lib/types";

export default function VerificationPage({ params }: PageProps<"/candidate/cv/[id]">) {
  return (
    <Page title="CV report">
      <Suspense fallback={<Loading />}>
        <Verification params={params} />
      </Suspense>
    </Page>
  );
}

async function Verification({ params }: { params: Promise<{ id: string }> }) {
  const me = await requireCandidate();
  const v = await myVerification(me.id, (await params).id);
  let answer: Report | Running;
  try {
    answer = await call<Report | Running>("m5", `/v1/verifications/${encodeURIComponent(v.id)}`);
  } catch (e) {
    if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
    throw e;
  }
  if (answer.status === "running") {
    return (
      <Card>
        <Refresh seconds={4} />
        <p>Checking {v.fileName}… This page updates by itself.</p>
        <p className="mt-1 text-sm text-muted">Started {new Date(answer.created_at).toLocaleTimeString("en-IN")}.</p>
      </Card>
    );
  }
  if (answer.status === "failed") {
    return <Card><p>{v.fileName} could not be checked: {answer.failure}</p></Card>;
  }
  if (!v.sentToM6At) {
    const report = answer;
    // After the response: a slow or absent M6 delays the evidence, never this page.
    after(() => forwardReport(v.id, report).catch(() => {}));
  }
  return (
    <>
      <p className="mb-4 text-sm text-muted">
        {v.fileName} · checked {new Date(answer.valid_as_of).toLocaleString("en-IN")}
      </p>
      <ReportView report={answer} marks={await marksFor(v.id)} mine />
    </>
  );
}
