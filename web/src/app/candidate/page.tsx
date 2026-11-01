import Link from "next/link";
import { Suspense } from "react";

import { applyToJob } from "@/app/candidate/actions";
import { ActionButton } from "@/components/action-button";
import { Chip, Empty, LinkButton, OrgBadge, OutcomeChip, Panel, STAGE_NOW, Stages } from "@/components/dashboard";
import { Icon } from "@/components/icons";
import { requireCandidate, TASK_JOB } from "@/lib/candidate";
import { db } from "@/lib/db";
import { outOf100, skillLabels } from "@/lib/skills";
import { call } from "@/lib/services";
import { day, when } from "@/lib/tasks";
import type { Job, Profile, Task } from "@/lib/types";

/** A developer's home: what needs them now, where their applications stand, roles they
 * can apply to, and what their profile shows. Each part reads its own module and says
 * so when it cannot; nothing here ranks or scores them. */
export default function CandidateHome() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <Suspense fallback={<Skeleton />}>
        <Home />
      </Suspense>
    </main>
  );
}

async function Home() {
  const me = await requireCandidate();
  const [cv, applications, assessments, openJobs, openCount] = await Promise.all([
    db.verification.findFirst({ where: { candidateId: me.id }, orderBy: { createdAt: "desc" } }),
    db.application.findMany({
      where: { candidateId: me.id }, include: { job: { include: { org: true } }, decision: true }, orderBy: { createdAt: "desc" },
    }),
    db.assessment.findMany({ where: { candidateId: me.id }, include: TASK_JOB, orderBy: { createdAt: "desc" } }),
    db.job.findMany({
      where: { open: true, applications: { none: { candidateId: me.id } } }, include: { org: true }, orderBy: { createdAt: "desc" }, take: 3,
    }),
    db.job.count({ where: { open: true, applications: { none: { candidateId: me.id } } } }),
  ]);
  // A module that is down leaves its part of the page empty-handed, not the page broken.
  const [tasks, jobs, profile, label] = await Promise.all([
    Promise.all(assessments.map((a) => call<Task>("assess", `/v1/sessions/${encodeURIComponent(a.id)}`).catch(() => null))),
    Promise.all(openJobs.map((j) => call<Job>("assess", `/v1/jobs/${encodeURIComponent(j.id)}`).catch(() => null))),
    call<Profile>("m6", `/developers/${encodeURIComponent(me.subjectRef)}/profile`).catch(() => null),
    skillLabels(),
  ]);

  // Waiting on the developer: tasks not yet submitted. A company's before practice, then
  // the soonest start-by first.
  const todo = assessments
    .map((a, i) => ({ id: a.id, job: a.application?.job ?? null, task: tasks[i] }))
    .filter((t): t is typeof t & { task: Task } => t.task?.status === "issued" || t.task?.status === "open")
    .sort((a, b) => Number(!a.job) - Number(!b.job) || (a.task.start_by ?? "~").localeCompare(b.task.start_by ?? "~"));

  // By name: the list shows skills, it does not rank them.
  const skills = [...(profile?.skills ?? [])].sort((a, b) => label(a.skill_id).localeCompare(label(b.skill_id)));
  const first = me.name.split(/\s+/)[0];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Welcome back, {first}</h1>
        <p className="mt-1 text-muted">{summary(todo.length, applications.length)}</p>
      </div>

      <NextStep todo={todo[0]} hasCv={!!cv} applied={applications.length > 0} openCount={openCount} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {todo.length > 0 && (
            <Panel title="Assessments to complete" href="/candidate/assessments" more="All assessments">
              <ul className="divide-y divide-line">
                {todo.map((t) => (
                  <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 py-3.5 first:pt-0 last:pb-0">
                    <div className="min-w-0">
                      <p className="font-medium">{t.task.title}</p>
                      <p className="text-sm text-muted">
                        {t.job ? `${t.job.org.name} · ${t.job.title}` : "Practice"} · {t.task.time_limit_minutes} min
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <TaskState task={t.task} />
                      <LinkButton href={`/candidate/assessments/${t.id}`}>{t.task.status === "open" ? "Continue" : "Open"}</LinkButton>
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          <Panel title="Your applications" href="/candidate/jobs" more="All jobs">
            {applications.length === 0 ? (
              <Empty
                icon="Briefcase" title="No applications yet"
                text="When you apply, you'll follow each one here from application to decision."
              />
            ) : (
              <ul className="space-y-4">
                {applications.map((a) => (
                  <li key={a.id} className="rounded-xl border border-line p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-3">
                        <OrgBadge name={a.job.org.name} />
                        <div className="min-w-0">
                          <p className="truncate font-medium">{a.job.title}</p>
                          <p className="text-sm text-muted">{a.job.org.name} · applied {day(a.createdAt)}</p>
                        </div>
                      </div>
                      {a.decision ? <OutcomeChip outcome={a.decision.outcome} /> : <Chip>{STAGE_NOW[a.status]}</Chip>}
                    </div>
                    <Stages status={a.status} />
                    {a.decision && (
                      <blockquote className="mt-3 rounded-lg bg-background px-4 py-3 text-sm">
                        <span className="mb-1 block text-xs font-medium text-muted">From the recruiter</span>
                        {a.decision.reason}
                      </blockquote>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Open roles" href="/candidate/jobs" more={openCount > openJobs.length ? `See all ${openCount}` : "All jobs"}>
            {openJobs.length === 0 ? (
              <Empty
                icon="Building" title={applications.length ? "You've applied to every open role" : "No open roles right now"}
                text="New roles appear here as companies open them. Practice in the meantime adds evidence to your skills."
              />
            ) : (
              <ul className="divide-y divide-line">
                {openJobs.map((j, i) => {
                  const must = jobs[i]?.skills.filter((s) => s.skill_id && s.priority === "must").map((s) => label(s.skill_id!)) ?? [];
                  return (
                    <li key={j.id} className="flex flex-wrap items-center justify-between gap-3 py-4 first:pt-0 last:pb-0">
                      <div className="flex min-w-0 items-center gap-3">
                        <OrgBadge name={j.org.name} />
                        <div className="min-w-0">
                          <p className="font-medium">{j.title}</p>
                          <p className="text-sm text-muted">{j.org.name}</p>
                          {must.length > 0 && (
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {must.map((s) => <Chip key={s}>{s}</Chip>)}
                            </div>
                          )}
                        </div>
                      </div>
                      <ActionButton action={applyToJob.bind(null, j.id)} label="Apply" />
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </div>

        <aside className="space-y-6">
          <Panel title="Your CV" href="/candidate/cv" more={cv ? "Manage" : undefined}>
            {cv ? (
              <div className="flex items-start gap-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent">
                  <Icon.File className="size-5" />
                </span>
                <div className="min-w-0">
                  <Link href={`/candidate/cv/${cv.id}`} className="block truncate font-medium hover:text-accent">{cv.fileName}</Link>
                  <p className="text-sm text-muted">Checked {day(cv.createdAt)}</p>
                  <p className={`mt-1 text-sm ${cv.sentToM6At ? "text-ok" : "text-muted"}`}>
                    {cv.sentToM6At ? "Added to your skills" : "Being added to your skills"}
                  </p>
                </div>
              </div>
            ) : (
              <Empty
                icon="Upload" title="Get your CV verified"
                text="We check what it claims against GitHub, Codeforces, LeetCode and live links. About a minute."
                action={<LinkButton href="/candidate/cv">Upload CV</LinkButton>}
              />
            )}
          </Panel>

          <Panel title="Your skills" href="/candidate/skills" more={skills.length ? "Details" : undefined}>
            {skills.length === 0 ? (
              <Empty
                icon="Spark" title="No skills on record yet"
                text={profile === null && cv ? "Your skills will appear once your CV has been added." : "Skills come from evidence: a verified CV or an assessment."}
              />
            ) : (
              <>
                <p className="mb-3 text-sm text-muted">
                  Scores out of 100, from your evidence. Recruiters see your skills with your applications.
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {skills.slice(0, 12).map((s) => (
                    <Link key={s.skill_id} href={`/candidate/skills/${encodeURIComponent(s.skill_id)}`}
                      className="flex items-center gap-1.5 rounded-full border border-line py-1 pr-1 pl-2.5 text-xs font-medium transition hover:border-accent hover:text-accent">
                      {label(s.skill_id)}
                      <span className="rounded-full bg-accent/10 px-1.5 py-0.5 font-semibold text-accent">{outOf100(s.score)}</span>
                    </Link>
                  ))}
                  {skills.length > 12 && <span className="px-1 py-1 text-xs text-muted">+{skills.length - 12} more</span>}
                </div>
              </>
            )}
          </Panel>

          <Link href="/candidate/assessments"
            className="group block rounded-2xl border border-line bg-panel p-5 transition hover:border-accent">
            <span className="flex items-center gap-2 font-semibold">
              <Icon.Code className="size-5 text-accent" /> Practice a task
              <Icon.Arrow className="ml-auto size-4 text-muted transition group-hover:translate-x-0.5 group-hover:text-accent" />
            </span>
            <span className="mt-1 block text-sm text-muted">
              Timed coding tasks, like the ones companies send. Each result adds to your skills.
            </span>
          </Link>
        </aside>
      </div>
    </div>
  );
}

function summary(todo: number, applied: number): string {
  if (todo) return `You have ${todo} assessment${todo === 1 ? "" : "s"} waiting for you.`;
  if (applied) return `You're following ${applied} application${applied === 1 ? "" : "s"}.`;
  return "Here's where your job search stands.";
}

/** The one thing most worth doing now, in this order: a company's task, a CV, a first
 * application, practice. */
function NextStep({ todo, hasCv, applied, openCount }: {
  todo?: { id: string; job: { title: string; org: { name: string } } | null; task: Task };
  hasCv: boolean; applied: boolean; openCount: number;
}) {
  let step: { title: string; text: string; href: string; cta: string };
  if (todo?.job) {
    step = {
      title: `${todo.job.org.name} sent you an assessment`,
      text: todo.task.status === "open"
        ? `${todo.task.title} is in progress. Finish before the timer runs out.`
        : `${todo.task.title} for ${todo.job.title}.${todo.task.start_by ? ` Start by ${when(todo.task.start_by)}.` : ""} The timer starts only when you press Start.`,
      href: `/candidate/assessments/${todo.id}`,
      cta: todo.task.status === "open" ? "Continue" : "View assessment",
    };
  } else if (!hasCv) {
    step = {
      title: "Start with your CV",
      text: "Upload it once and we'll check its claims against your public work. Recruiters see verified evidence, not just keywords.",
      href: "/candidate/cv", cta: "Upload CV",
    };
  } else if (!applied && openCount > 0) {
    step = {
      title: `${openCount} open role${openCount === 1 ? " is" : "s are"} waiting`,
      text: "Your verified CV goes with every application. Apply in one click.",
      href: "/candidate/jobs", cta: "Browse jobs",
    };
  } else {
    step = {
      title: "Keep your skills sharp",
      text: "A practice task adds direct evidence to your skills, and shows you what an assessment feels like.",
      href: "/candidate/assessments", cta: "Practice",
    };
  }
  return (
    <section className="auth-panel relative overflow-hidden rounded-2xl px-6 py-6 text-white sm:px-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold tracking-wider text-white/70 uppercase">Next step</p>
          <h2 className="mt-1 text-xl font-bold sm:text-2xl">{step.title}</h2>
          <p className="mt-1.5 text-white/80">{step.text}</p>
        </div>
        <Link href={step.href}
          className="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-2.5 font-semibold text-[#0f3d3a] shadow-sm transition hover:bg-white/90">
          {step.cta} <Icon.Arrow className="size-4" />
        </Link>
      </div>
    </section>
  );
}

/** Whether an unsubmitted task has started, and its deadline to start if it has not. */
function TaskState({ task }: { task: Task }) {
  if (task.status === "open") {
    return <Chip tone="accent">In progress · {task.attempts_used}/{task.max_attempts} submissions</Chip>;
  }
  return task.start_by
    ? <span className="flex items-center gap-1.5 text-sm text-muted"><Icon.Clock className="size-4" /> Start by {when(task.start_by)}</span>
    : <Chip>Not started</Chip>;
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-8" aria-label="Loading">
      <div className="h-9 w-64 rounded-lg bg-line" />
      <div className="h-32 rounded-2xl bg-line" />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="h-72 rounded-2xl bg-line lg:col-span-2" />
        <div className="h-72 rounded-2xl bg-line" />
      </div>
    </div>
  );
}
