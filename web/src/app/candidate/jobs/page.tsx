import { Suspense } from "react";

import { applyToJob } from "@/app/candidate/actions";
import { ActionButton } from "@/components/action-button";
import { Card, Loading, Page } from "@/components/ui";
import Link from "next/link";

import { requireCandidate } from "@/lib/candidate";
import { inboxFor } from "@/lib/chat";
import { db } from "@/lib/db";
import { call, ServiceError } from "@/lib/services";
import type { Job } from "@/lib/types";

export default function JobsPage() {
  return (
    <Page title="Jobs">
      <Suspense fallback={<Loading />}>
        <Jobs />
      </Suspense>
    </Page>
  );
}

async function Jobs() {
  const me = await requireCandidate();
  const [open, mine] = await Promise.all([
    db.job.findMany({ where: { open: true }, include: { org: true }, orderBy: { createdAt: "desc" } }),
    db.application.findMany({ where: { candidateId: me.id }, include: { job: { include: { org: true } }, decision: true }, orderBy: { createdAt: "desc" } }),
  ]);
  const applied = new Set(mine.map((a) => a.jobId));
  const chats = new Map((await inboxFor(me).catch((e: unknown) => {
    if (e instanceof ServiceError) return [];
    throw e;
  })).map((r) => [r.thread_id, r.unread]));
  const skills = await Promise.all(open.map((j) => call<Job>("assess", `/v1/jobs/${encodeURIComponent(j.id)}`).catch(() => null)));
  return (
    <div className="space-y-4">
      {mine.length > 0 && (
        <Card>
          <h2 className="mb-2 font-semibold">Your applications</h2>
          <ul className="space-y-2">
            {mine.map((a) => (
              <li key={a.id}>
                {a.job.title} <span className="text-sm text-muted">· {a.job.org.name} · {a.status.toLowerCase().replace("_", " ")}</span>
                {chats.has(a.id) && (
                  <Link href={`/candidate/messages/${a.id}`} className="ml-2 text-sm text-accent underline">
                    Chat with the recruiter{chats.get(a.id) ? ` (${chats.get(a.id)} unread)` : ""}
                  </Link>
                )}
                {a.decision && (
                  <p className="text-sm">Decision: {a.decision.outcome.toLowerCase()}. <q>{a.decision.reason}</q></p>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card>
        <h2 className="mb-2 font-semibold">Open</h2>
        {open.length === 0 && <p className="text-sm text-muted">No open jobs.</p>}
        <ul className="space-y-3">
          {open.map((j, i) => (
            <li key={j.id} className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-medium">{j.title}</p>
                <p className="text-sm text-muted">{j.org.name}</p>
                {skills[i] && (
                  <p className="text-sm">
                    Must-haves: {skills[i]!.skills.filter((s) => s.skill_id && s.priority === "must").map((s) => s.skill_id).join(", ")}
                  </p>
                )}
              </div>
              {applied.has(j.id) ? <span className="text-sm text-muted">applied</span>
                : <ActionButton action={applyToJob.bind(null, j.id)} label="Apply" />}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
