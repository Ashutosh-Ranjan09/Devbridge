import Link from "next/link";
import { Suspense } from "react";

import { UploadCv } from "@/components/candidate";
import { Card, Loading, Page } from "@/components/ui";
import { requireCandidate } from "@/lib/candidate";
import { db } from "@/lib/db";

export default function CvPage() {
  return (
    <Page title="Your CV">
      <div className="space-y-4">
        <Card>
          <h2 className="mb-1 font-semibold">Check a CV</h2>
          <p className="mb-3 text-sm text-muted">
            PDF or Word, up to 5 MB. Its claims are checked against GitHub, Codeforces, LeetCode, CodeChef and
            live links. It takes about a minute. Text that is hidden in the file is never read by a model,
            and is reported.
          </p>
          <Suspense fallback={<Loading />}>
            <Upload />
          </Suspense>
        </Card>
        <Suspense fallback={<Loading />}>
          <History />
        </Suspense>
      </div>
    </Page>
  );
}

async function Upload() {
  const me = await requireCandidate();
  const c = await db.candidate.findUniqueOrThrow({ where: { userId: me.id } });
  const saved = { github: c.githubHandle, codeforces: c.codeforcesHandle, leetcode: c.leetcodeHandle, codechef: c.codechefHandle };
  return <UploadCv saved={Object.fromEntries(Object.entries(saved).filter(([, v]) => v !== null)) as Record<string, string>} />;
}

async function History() {
  const me = await requireCandidate();
  const rows = await db.verification.findMany({ where: { candidateId: me.id }, orderBy: { createdAt: "desc" } });
  if (!rows.length) return null;
  return (
    <Card>
      <h2 className="mb-2 font-semibold">Checked before</h2>
      <ul className="space-y-1">
        {rows.map((v) => (
          <li key={v.id} className="flex flex-wrap gap-x-3">
            <Link href={`/candidate/cv/${v.id}`} className="text-accent underline">{v.fileName}</Link>
            <span className="text-sm text-muted">{v.createdAt.toLocaleString("en-IN")}</span>
            <span className="text-sm text-muted">{v.sentToM6At ? "in your skill graph" : "not in your skill graph yet"}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
