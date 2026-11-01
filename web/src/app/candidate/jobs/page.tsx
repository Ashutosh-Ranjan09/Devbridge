import { Suspense } from "react";

import { Chip, Empty, LinkButton, OrgBadge, OutcomeChip, Panel, STAGE_NOW, Stages } from "@/components/dashboard";
import { type Role, RoleBrowser } from "@/components/jobs";
import { requireCandidate } from "@/lib/candidate";
import { inboxFor } from "@/lib/chat";
import { db } from "@/lib/db";
import { call, ServiceError } from "@/lib/services";
import { skillLabels } from "@/lib/skills";
import { day } from "@/lib/tasks";
import type { Job, Task } from "@/lib/types";

export default function JobsPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Jobs</h1>
        <p className="mt-1 max-w-2xl text-muted">
          Apply in one click. Your verified CV and skills go with every application, and a person reads them and decides.
        </p>
      </div>
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-line" />}>
        <Jobs />
      </Suspense>
    </main>
  );
}

async function Jobs() {
  const me = await requireCandidate();
  const [open, mine] = await Promise.all([
    db.job.findMany({ where: { open: true }, include: { org: true }, orderBy: { createdAt: "desc" } }),
    db.application.findMany({
      where: { candidateId: me.id },
      include: { job: { include: { org: true } }, decision: true, assessments: { orderBy: { createdAt: "desc" } } },
      orderBy: { createdAt: "desc" },
    }),
  ]);
  const applied = new Set(mine.map((a) => a.jobId));
  // A module that is down leaves a role without its skills and description, not the page broken.
  const [details, label, tasks] = await Promise.all([
    Promise.all(open.map((j) => call<Job>("assess", `/v1/jobs/${encodeURIComponent(j.id)}`).catch(() => null))),
    skillLabels(),
    Promise.all(mine.map((a) => a.assessments[0]
      ? call<Task>("assess", `/v1/sessions/${encodeURIComponent(a.assessments[0].id)}`).catch(() => null)
      : null)),
  ]);
  // The chats a recruiter has opened, with what is unread; none when the chat module is down.
  const chats = new Map((await inboxFor(me).catch((e: unknown) => {
    if (e instanceof ServiceError) return [];
    throw e;
  })).map((r) => [r.thread_id, r.unread]));
  const name = (s: Job["skills"][number]) => (s.skill_id ? label(s.skill_id) : s.surface);
  const roles: Role[] = open.map((j, i) => ({
    id: j.id, title: j.title, org: j.org.name, posted: day(j.createdAt), applied: applied.has(j.id),
    must: details[i]?.skills.filter((s) => s.priority === "must").map(name) ?? [],
    nice: details[i]?.skills.filter((s) => s.priority === "nice").map(name) ?? [],
    text: details[i]?.text ?? null,
  }));

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_380px]">
      <section className="min-w-0">
        <h2 className="mb-4 font-semibold">Open roles</h2>
        <RoleBrowser roles={roles} />
      </section>

      <aside className="lg:sticky lg:top-20 lg:self-start">
        <Panel title={`My applications${mine.length ? ` (${mine.length})` : ""}`}>
          {mine.length === 0 ? (
            <Empty icon="Briefcase" title="No applications yet" text="Apply to a role and follow it here, from application to decision." />
          ) : (
            <ul className="space-y-4">
              {mine.map((a, i) => {
                const t = tasks[i];
                const todo = t && (t.status === "issued" || t.status === "open");
                return (
                  <li key={a.id} className="rounded-xl border border-line p-4">
                    <div className="flex items-start gap-3">
                      <OrgBadge name={a.job.org.name} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{a.job.title}</p>
                        <p className="text-xs text-muted">{a.job.org.name} · applied {day(a.createdAt)}</p>
                      </div>
                    </div>
                    <div className="mt-3">{a.decision ? <OutcomeChip outcome={a.decision.outcome} /> : <Chip>{STAGE_NOW[a.status]}</Chip>}</div>
                    <Stages status={a.status} />
                    {a.decision && (
                      <blockquote className="mt-3 rounded-lg bg-background px-3 py-2.5 text-sm">
                        <span className="mb-0.5 block text-xs font-medium text-muted">From the recruiter</span>
                        {a.decision.reason}
                      </blockquote>
                    )}
                    {t && a.assessments[0] && (
                      <div className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-accent/5 px-3 py-2 text-sm">
                        <span className="min-w-0 truncate">{todo ? "Assessment waiting" : "Assessment"}: {t.title}</span>
                        <LinkButton href={`/candidate/assessments/${a.assessments[0].id}`}>
                          {t.status === "open" ? "Continue" : t.status === "issued" ? "Open" : "View"}
                        </LinkButton>
                      </div>
                    )}
                    {chats.has(a.id) && (
                      <div className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-accent/5 px-3 py-2 text-sm">
                        <span className="min-w-0 truncate">
                          Chat with the recruiter{chats.get(a.id) ? ` · ${chats.get(a.id)} unread` : ""}
                        </span>
                        <LinkButton href={`/candidate/messages/${a.id}`}>Open</LinkButton>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>
      </aside>
    </div>
  );
}
