import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { MarkForm } from "@/components/admin";
import { CandidateNote, ReportView } from "@/components/report";
import { Card, Loading, Page } from "@/components/ui";
import { requireRole } from "@/lib/auth";
import { db } from "@/lib/db";
import { alsoChecked, m5Rules } from "@/lib/m5";
import { marksFor } from "@/lib/review";
import { call, ServiceError } from "@/lib/services";
import type { Report, Running } from "@/lib/types";

export default function CandidateReviewPage({ params, searchParams }: PageProps<"/admin/candidates/[userId]">) {
  return (
    <Page title="Candidate">
      <Suspense fallback={<Loading />}>
        <CandidateReview params={params} searchParams={searchParams} />
      </Suspense>
    </Page>
  );
}

/** One candidate's CV reports, each line with M5's reading and an admin's mark beside it.
 * The mark never changes the report, and never reaches M6: it is a person's note on a line. */
async function CandidateReview({ params, searchParams }: {
  params: Promise<{ userId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await requireRole("ADMIN");
  const { userId } = await params;
  const { v } = await searchParams;
  const person = await db.user.findFirst({
    where: { id: userId, role: "CANDIDATE" },
    select: {
      name: true, email: true,
      candidate: {
        select: {
          subjectRef: true,
          verifications: { orderBy: { createdAt: "desc" }, select: { id: true, fileName: true, createdAt: true, note: true } },
        },
      },
    },
  }) ?? notFound();
  const cvs = person.candidate?.verifications ?? [];
  const chosen = cvs.find((c) => c.id === v) ?? cvs[0];

  const header = (
    <Card>
      <p className="font-semibold">{person.name}</p>
      <p className="text-sm text-muted">{person.email} · known to the modules as <code>{person.candidate?.subjectRef}</code></p>
      {cvs.length > 1 && (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {cvs.map((c) => (
            <li key={c.id}>
              <Link href={`/admin/candidates/${userId}?v=${encodeURIComponent(c.id)}`}
                className={c.id === chosen?.id ? "font-semibold" : "text-accent hover:underline"}>
                {c.fileName} · {c.createdAt.toLocaleDateString("en-IN")}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-muted">
        Mark a line once you have checked it yourself, and say what you looked at. The candidate and
        recruiters see the mark as an admin&apos;s, beside M5&apos;s own reading; it does not change their skills.
      </p>
    </Card>
  );
  if (!chosen) return <div className="space-y-4">{header}<Card><p>No CV uploaded yet.</p></Card></div>;

  const [report, marks, rules] = await Promise.all([
    call<Report | Running>("m5", `/v1/verifications/${encodeURIComponent(chosen.id)}`)
      .catch((e: unknown) => (e instanceof ServiceError ? e : Promise.reject(e))),
    marksFor(chosen.id, { names: true }),
    m5Rules(),
  ]);
  return (
    <div className="space-y-4">
      {header}
      <p className="text-sm text-muted">{chosen.fileName} · uploaded {chosen.createdAt.toLocaleString("en-IN")}</p>
      <CandidateNote note={chosen.note} />
      {report instanceof ServiceError ? <Card><p>{report.message}</p></Card>
        : report.status === "running" ? <Card><p>Still being checked.</p></Card>
        : report.status === "failed" ? <Card><p>Could not be checked: {report.failure}</p></Card>
        : <ReportView report={report} marks={marks} alsoChecked={alsoChecked(report, rules)}
            review={(key) => <MarkForm userId={userId} verificationId={chosen.id} lineKey={key} />} />}
    </div>
  );
}
