import { Suspense } from "react";

import { StartPractice } from "@/components/candidate";
import { Chip, Empty, LinkButton, Panel } from "@/components/dashboard";
import { Icon } from "@/components/icons";
import { myPractice, requireCandidate, TASK_JOB } from "@/lib/candidate";
import { db } from "@/lib/db";
import { call, ServiceError } from "@/lib/services";
import { skillLabels } from "@/lib/skills";
import { PRACTISED, when } from "@/lib/tasks";
import type { Pattern, Task } from "@/lib/types";

export default function AssessmentsPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Assessments</h1>
        <p className="mt-1 max-w-2xl text-muted">
          Timed coding tasks in a real editor. Each one is your own version, equally hard for everyone, and every result adds to your skills.
        </p>
      </div>
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-line" />}>
        <Assessments />
      </Suspense>
    </main>
  );
}

async function Assessments() {
  const me = await requireCandidate();
  const rows = await db.assessment.findMany({ where: { candidateId: me.id, applicationId: { not: null } }, orderBy: { createdAt: "desc" }, include: TASK_JOB });
  let patterns: Pattern[];
  let tasks: (Task | null)[];
  try {
    [patterns, tasks] = await Promise.all([
      call<Pattern[]>("assess", "/v1/patterns"),
      Promise.all(rows.map((r) => call<Task>("assess", `/v1/sessions/${encodeURIComponent(r.id)}`).catch(() => null))),
    ]);
  } catch (e) {
    if (e instanceof ServiceError) return <Panel title="Assessments"><p className="text-muted">{e.message}</p></Panel>;
    throw e;
  }
  const [label, practised] = await Promise.all([skillLabels(), myPractice(me.id)]);

  return (
    <div className="space-y-8">
      <Panel title="From companies">
        {rows.length === 0 ? (
          <Empty icon="Briefcase" title="No company assessments yet"
            text="When a company you've applied to sends one, it appears here with its start-by date." />
        ) : (
          <ul className="divide-y divide-line">
            {rows.map((r, i) => {
              const t = tasks[i];
              const job = r.application!.job;
              return (
                <li key={r.id} className="flex flex-wrap items-center gap-4 py-4 first:pt-0 last:pb-0">
                  <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent/10 text-sm font-semibold text-accent">
                    {job.org.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{t?.title ?? "Assessment"}</p>
                    <p className="text-sm text-muted">
                      {job.org.name} · {job.title}{t ? ` · ${t.time_limit_minutes} min` : ""}
                    </p>
                  </div>
                  <Status task={t} />
                  {t && <LinkButton href={`/candidate/assessments/${r.id}`}>{ACTION[t.status]}</LinkButton>}
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      <section>
        <div className="mb-4">
          <h2 className="font-semibold">Practice</h2>
          <p className="mt-0.5 text-sm text-muted">One go at each task. Your result becomes evidence for its skill.</p>
        </div>
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {patterns.map((p) => {
            const mine = practised.get(p.id);
            return (
              <li key={p.id} className="flex flex-col rounded-2xl border border-line bg-panel p-5">
                <div className="flex items-start justify-between gap-3">
                  <span className="grid size-10 place-items-center rounded-xl bg-accent/10 text-accent"><Icon.Code className="size-5" /></span>
                  <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${LEVEL[p.level] ?? "bg-background text-muted"}`}>{cap(p.level)}</span>
                </div>
                <p className="mt-4 font-semibold">{p.title}</p>
                <p className="mt-1 text-sm text-muted">Builds {label(p.skill)}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Chip>{p.time_limit_minutes} min</Chip>
                  <Chip>Python</Chip>
                  {mine && <Chip tone="accent">{mine.status === "submitted" ? "Done" : mine.status === "open" ? "In progress" : mine.status === "expired" ? "Expired" : "Not started"}</Chip>}
                </div>
                <div className="mt-auto pt-5">
                  {mine ? <LinkButton href={`/candidate/assessments/${mine.id}`}>{PRACTISED[mine.status]}</LinkButton> : <StartPractice patternId={p.id} />}
                </div>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const LEVEL: Record<string, string> = {
  easy: "bg-ok/10 text-ok",
  medium: "bg-highlight/15 text-[#b45309] dark:text-highlight",
  hard: "bg-danger/10 text-danger",
};

const ACTION: Record<Task["status"], string> = { issued: "View", open: "Continue", submitted: "See result", expired: "View" };

function Status({ task }: { task: Task | null }) {
  if (!task) return <Chip>Unavailable</Chip>;
  if (task.status === "issued") {
    return task.start_by
      ? <span className="flex items-center gap-1.5 text-sm text-muted"><Icon.Clock className="size-4" /> Start by {when(task.start_by)}</span>
      : <Chip>Not started</Chip>;
  }
  if (task.status === "open") return <Chip tone="accent">In progress · {task.attempts_used}/{task.max_attempts} submitted</Chip>;
  if (task.status === "submitted") return <Chip tone="accent">Submitted</Chip>;
  return <Chip>{task.started_at ? "Expired" : "Expired · never started"}</Chip>;
}
