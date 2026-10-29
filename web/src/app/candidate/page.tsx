import Link from "next/link";
import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { requireCandidate } from "@/lib/candidate";
import { db } from "@/lib/db";

export default function CandidateHome() {
  return (
    <Page title="Your profile">
      <Suspense fallback={<Loading />}>
        <Overview />
      </Suspense>
    </Page>
  );
}

async function Overview() {
  const me = await requireCandidate();
  const [cvs, tasks, applications] = await Promise.all([
    db.verification.count({ where: { candidateId: me.id } }),
    db.assessment.count({ where: { candidateId: me.id } }),
    db.application.count({ where: { candidateId: me.id } }),
  ]);
  return (
    <div className="space-y-4">
      <Card>
        <p>Signed in as {me.name} ({me.email}).</p>
        <p className="mt-2 text-sm text-muted">
          The modules know you only as <code>{me.subjectRef}</code>, never by name or email.
        </p>
      </Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Step href="/candidate/cv" title="1. Your CV" text={`${cvs} checked. Upload one to have its claims checked against the systems it names.`} />
        <Step href="/candidate/skills" title="2. Your skills" text="Measured from that evidence, as ranges, never one score." />
        <Step href="/candidate/assessments" title="3. Assessments" text={`${tasks} taken. A coding task in a sandbox adds direct evidence.`} />
        <Step href="/candidate/jobs" title="4. Jobs" text={`${applications} application(s). A person reads your evidence and decides, and says why.`} />
      </div>
    </div>
  );
}

function Step({ href, title, text }: { href: string; title: string; text: string }) {
  return (
    <Link href={href} className="block rounded-lg border border-line bg-panel p-4 hover:border-accent">
      <h2 className="font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-muted">{text}</p>
    </Link>
  );
}
