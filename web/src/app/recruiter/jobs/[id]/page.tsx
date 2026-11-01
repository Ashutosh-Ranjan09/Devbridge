import Link from "next/link";
import { after } from "next/server";
import { type ReactNode, Suspense } from "react";

import { ActionButton } from "@/components/action-button";
import { OrgBadge } from "@/components/dashboard";
import { type ApplicantRow, ApplicantBoard, Avatar, JobState } from "@/components/hiring";
import { Icon } from "@/components/icons";
import { SkillEditor } from "@/components/recruiter";
import { confirmJob, setOpen } from "@/app/recruiter/actions";
import { db } from "@/lib/db";
import { basisText } from "@/lib/match";
import { myJob, requireRecruiter } from "@/lib/recruiter";
import { call, ServiceError } from "@/lib/services";
import { settleAssessment } from "@/lib/sync";
import { day, forApplicants, pendingStatus } from "@/lib/tasks";
import type { Job, JobResults, JobTasks, Requirements, Shortlist, ShortlistEntry } from "@/lib/types";

export default function JobPage({ params, searchParams }: PageProps<"/recruiter/jobs/[id]">) {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <Link href="/recruiter" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-accent">
        <Icon.Chevron className="size-4 rotate-90" /> All jobs
      </Link>
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-line" />}>
        <JobView params={params} searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

const TABS = [["applicants", "Applicants"], ["results", "Assessment results"], ["requirements", "Requirements"]] as const;
type Tab = (typeof TABS)[number][0];

function Problem({ children }: { children: ReactNode }) {
  return <p className="rounded-2xl border border-danger/30 bg-danger/5 px-5 py-4 text-sm">{children}</p>;
}

async function JobView({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const me = await requireRecruiter();
  const row = await myJob(me.orgIds, (await params).id);
  let job: Job;
  let tasks: JobTasks;
  try {
    [job, tasks] = await Promise.all([
      call<Job>("assess", `/v1/jobs/${encodeURIComponent(row.id)}`),
      call<JobTasks>("assess", `/v1/jobs/${encodeURIComponent(row.id)}/tasks`),
    ]);
  } catch (e) {
    if (e instanceof ServiceError) return <Problem>{e.message}</Problem>;
    throw e;
  }
  const catalogue = await call<{ skills: { skill_id: string; label?: string }[] }>("m6", "/skills").then(
    (r) => r.skills.map((s) => ({ id: s.skill_id, label: s.label ?? s.skill_id })), () => [],
  );
  const names = new Map(catalogue.map((c) => [c.id, c.label]));
  const label = (id: string) => names.get(id) ?? id;
  const draft = job.status === "proposed";

  const head = (
    <div className="mb-6 flex flex-wrap items-start gap-4">
      <OrgBadge name={row.org.name} />
      <div className="min-w-0 flex-1">
        <h1 className="flex flex-wrap items-center gap-3 text-2xl font-bold tracking-tight sm:text-3xl">
          {row.title} <JobState state={draft ? "draft" : row.open ? "listed" : "closed"} />
        </h1>
        <p className="mt-1 text-sm text-muted">
          {row.org.name} · posted {day(row.createdAt)}
          {job.confirmed_by && job.confirmed_at && ` · confirmed by ${job.confirmed_by.replace(/\s*<.*>$/, "")} on ${day(job.confirmed_at)}`}
        </p>
      </div>
      {!draft && (
        <div className="basis-full sm:basis-auto">
        <ActionButton action={setOpen.bind(null, row.id, !row.open)} variant={row.open ? "outline" : "solid"}
          label={row.open ? "Close applications" : "Open for applications"} />
        </div>
      )}
    </div>
  );

  if (draft) {
    return (
      <>
        {head}
        <ol className="mb-6 grid grid-cols-3 gap-2 text-xs sm:text-sm" aria-label="Progress">
          {["Description", "Review skills & tasks", "Open applications"].map((s, i) => (
            <li key={s} aria-current={i === 1 ? "step" : undefined}>
              <span className={`block h-1.5 rounded-full ${i <= 1 ? "bg-accent" : "bg-line"}`} />
              <span className={`mt-1.5 flex items-center gap-1 ${i === 1 ? "font-semibold" : "text-muted"}`}>
                {i === 0 && <Icon.Check className="size-3.5 text-accent" />}{s}
              </span>
            </li>
          ))}
        </ol>
        {job.dropped_unquoted > 0 && (
          <p className="mb-4 rounded-xl bg-background px-4 py-3 text-sm text-muted ring-1 ring-line">
            {job.dropped_unquoted} proposed skill{job.dropped_unquoted > 1 ? "s were" : " was"} left out: the words quoted for it aren&apos;t in your description.
          </p>
        )}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
          <section className="rounded-2xl border border-line bg-panel p-5 sm:p-7">
            <SkillEditor jobId={row.id} skills={job.skills} catalogue={catalogue} tasks={tasks} />
          </section>
          <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
            <div className="rounded-2xl border border-accent/40 bg-accent/5 p-5">
              <p className="font-semibold">Happy with it?</p>
              <p className="mt-1 mb-4 text-sm text-muted">
                Save your changes first. Confirming locks the skills and tasks, and then you can open the job to applicants.
              </p>
              <ActionButton action={confirmJob.bind(null, row.id)} label="Confirm skills & tasks" />
            </div>
            <JobText text={job.text} />
          </aside>
        </div>
      </>
    );
  }

  const asked = (await searchParams).tab;
  const tab: Tab = TABS.some(([t]) => t === asked) ? (asked as Tab) : "applicants";
  const count = await db.application.count({ where: { jobId: row.id } });
  const must = job.skills.filter((s) => s.skill_id && s.priority === "must");
  return (
    <>
      {head}
      <nav className="mb-6 flex gap-1 overflow-x-auto border-b border-line" aria-label="Job sections">
        {TABS.map(([t, text]) => (
          <Link key={t} href={t === "applicants" ? "?" : `?tab=${t}`} aria-current={tab === t ? "page" : undefined}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-semibold whitespace-nowrap transition ${tab === t ? "border-accent text-accent" : "border-transparent text-muted hover:text-foreground"}`}>
            {text}{t === "applicants" && <span className="ml-1.5 rounded-full bg-background px-1.5 text-xs ring-1 ring-line">{count}</span>}
          </Link>
        ))}
      </nav>
      {tab === "applicants" && <Applicants jobId={row.id} skills={must.map((s) => s.skill_id as string)} label={label} />}
      {tab === "results" && <Results jobId={row.id} />}
      {tab === "requirements" && <RequirementsView job={job} tasks={tasks} label={label} />}
    </>
  );
}

function JobText({ text }: { text: string }) {
  return (
    <details className="group rounded-2xl border border-line bg-panel p-5">
      <summary className="flex cursor-pointer list-none items-center justify-between font-semibold">
        Job description <Icon.Chevron className="size-4 text-muted transition group-open:rotate-180" />
      </summary>
      <p className="mt-3 max-h-[50vh] overflow-y-auto text-sm leading-relaxed whitespace-pre-line text-muted">{text}</p>
    </details>
  );
}

type App = { id: string; createdAt: Date; status: ApplicantRow["status"]; candidate: { subjectRef: string; user: { name: string } }; decision: { outcome: ApplicantRow["outcome"] & string } | null };

async function applicantsOf(jobId: string): Promise<App[]> {
  const apps = await db.application.findMany({
    where: { jobId },
    include: { candidate: { include: { user: true } }, decision: true },
  });
  // By name: a list of people, never ordered by any skill.
  return apps.sort((a, b) => a.candidate.user.name.localeCompare(b.candidate.user.name));
}

/** The job's results from the assessment module, and each final one told to M6 and the
 * application: settled by the deadline with nobody pressing a button. */
async function resultsOf(jobId: string, apps: App[]) {
  const sessions = await db.assessment.findMany({ where: { applicationId: { in: apps.map((a) => a.id) } } });
  if (!sessions.length) return { sessions, results: null };
  const results = await call<JobResults>("assess", `/v1/jobs/${encodeURIComponent(jobId)}/results`)
    .catch((e: unknown) => (e instanceof ServiceError ? e : Promise.reject(e)));
  if (!(results instanceof ServiceError)) {
    const settled = new Set(results.tasks.flatMap((t) => t.ranked.map((r) => r.session_id)));
    for (const s of sessions) if (settled.has(s.id) && !s.sentToM6At) after(() => settleAssessment(s.id).catch(() => {}));
  }
  return { sessions, results };
}

async function Applicants({ jobId, skills, label }: { jobId: string; skills: string[]; label: (id: string) => string }) {
  const apps = await applicantsOf(jobId);
  if (!apps.length) return <ApplicantBoard jobId={jobId} applicants={[]} shortlistNote={null} />;

  // M6 down: the board still shows, without the must-haves.
  let shortlist: Shortlist | ServiceError;
  try {
    const requirements = await call<Requirements>("assess", `/v1/jobs/${encodeURIComponent(jobId)}/requirements`);
    const subjects = apps.map((a) => `subject=${encodeURIComponent(a.candidate.subjectRef)}`).join("&");
    shortlist = await call<Shortlist>("m6", `/shortlist?${subjects}`, { body: requirements });
  } catch (e) {
    if (!(e instanceof ServiceError)) throw e;
    shortlist = e;
  }
  const { results } = await resultsOf(jobId, apps);
  const entries = new Map<string, ShortlistEntry & { clearsAll: boolean }>(shortlist instanceof ServiceError ? [] : [
    ...shortlist.candidates.map((c) => [c.subject_ref, { ...c, clearsAll: true }] as const),
    ...shortlist.others.map((c) => [c.subject_ref, { ...c, clearsAll: false }] as const),
  ]);
  const total = results && !(results instanceof ServiceError) ? results.assessment : null;

  const rows = apps.map((a): ApplicantRow => {
    const ref = a.candidate.subjectRef;
    const entry = entries.get(ref);
    const done = total?.ranked.find((r) => r.candidate_ref === ref);
    return {
      id: a.id, name: a.candidate.user.name, applied: day(a.createdAt), status: a.status, outcome: a.decision?.outcome ?? null,
      clearsAll: entry ? entry.clearsAll : null,
      match: entry?.job_match ?? null,
      musts: skills.map((skill) => ({
        skill, label: label(skill), clears: entry?.clears[skill] ?? null,
        interval: entry?.must[skill]?.interval ?? null, inferred: !!entry?.must[skill]?.inferred,
      })),
      test: done ? { points: done.points, outOf: done.out_of } : total?.in_progress.some((w) => w.candidate_ref === ref) ? "testing" : null,
    };
  });
  return (
    <div className="space-y-4">
      {shortlist instanceof ServiceError && <Problem>Must-haves aren&apos;t available right now: {shortlist.message}</Problem>}
      {results instanceof ServiceError && <Problem>Assessment results aren&apos;t available right now: {results.message}</Problem>}
      <ApplicantBoard jobId={jobId} applicants={rows} shortlistNote={shortlist instanceof ServiceError ? null
        : `Clears every bar: ${shortlist.match}. ${basisText(shortlist.job_match_basis)} The match filters nobody.`} />
    </div>
  );
}

function RequirementsView({ job, tasks, label }: { job: Job; tasks: JobTasks; label: (id: string) => string }) {
  const must = job.skills.filter((s) => s.skill_id && s.priority === "must");
  const nice = job.skills.filter((s) => s.skill_id && s.priority === "nice");
  const chosen = Object.entries(tasks.must).flatMap(([skill, list]) => list.filter((o) => o.chosen).map((o) => ({ ...o, skill })));
  const minutes = chosen.reduce((sum, o) => sum + o.time_limit_minutes, 0);
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-6">
        <section className="rounded-2xl border border-line bg-panel p-5 sm:p-6">
          <h2 className="mb-4 font-semibold">Must-haves <span className="font-normal text-muted">· {must.length}</span></h2>
          <ul className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {must.map((s) => (
              <li key={s.skill_id} className="rounded-xl border border-line p-4">
                <p className="font-semibold">{label(s.skill_id as string)}</p>
                <p className="mt-0.5 text-sm text-muted">
                  {s.bar === null ? "Assessed, not filtered" : s.bar === 0 ? "Any direct evidence" : `Bar ${s.bar.toFixed(2)}`}
                </p>
                <p className="mt-2 line-clamp-2 text-xs text-muted">&ldquo;{s.quote}&rdquo;</p>
              </li>
            ))}
          </ul>
          {nice.length > 0 && (
            <>
              <h3 className="mt-6 mb-2 text-sm font-semibold">Nice to have</h3>
              <ul className="flex flex-wrap gap-1.5">
                {nice.map((s) => <li key={s.skill_id} className="rounded-md bg-background px-2 py-1 text-xs font-medium ring-1 ring-line">{label(s.skill_id as string)}</li>)}
              </ul>
            </>
          )}
        </section>
        <section className="rounded-2xl border border-line bg-panel p-5 sm:p-6">
          <h2 className="font-semibold">The assessment</h2>
          <p className="mt-0.5 mb-4 text-sm text-muted">
            {chosen.length ? `Every applicant gets the same ${chosen.length} task${chosen.length > 1 ? "s" : ""}, ${minutes} minutes in all.` : "No tasks: nothing is sent to applicants."}
          </p>
          <ul className="space-y-2.5">
            {chosen.map((o) => (
              <li key={o.pattern_id} className="flex items-center gap-3 rounded-xl border border-line p-3.5">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent"><Icon.Code className="size-[18px]" /></span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{o.title}</p>
                  <p className="text-xs text-muted">{label(o.skill)} · <span className="capitalize">{o.level}</span></p>
                </div>
                <span className="flex items-center gap-1 text-sm text-muted"><Icon.Clock className="size-4" />{o.time_limit_minutes} min</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <aside className="lg:self-start"><JobText text={job.text} /></aside>
    </div>
  );
}

type Who = { name: string; appId: string };

/** Each task's results ranked on its own, as the assessment module ranks them: hidden
 * tests passed, then time taken. Never summed across tasks. A person picks from here and
 * decides on the applicant's page. */
async function Results({ jobId }: { jobId: string }) {
  const apps = await applicantsOf(jobId);
  const { sessions, results } = await resultsOf(jobId, apps);
  if (!results) {
    return (
      <div className="rounded-2xl border border-dashed border-line bg-panel px-6 py-14 text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-full bg-accent/10 text-accent"><Icon.Code className="size-6" /></span>
        <p className="mt-4 font-semibold">No assessments sent yet</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted">Send one from an applicant&apos;s page. Results show here as candidates finish.</p>
      </div>
    );
  }
  if (results instanceof ServiceError) return <Problem>{results.message}</Problem>;
  const names = new Map(apps.map((a) => [a.id, a.candidate.user.name]));
  const who = new Map<string, Who>(sessions.map((s) => [s.id, { name: names.get(s.applicationId ?? "") ?? "?", appId: s.applicationId ?? "" }]));
  const bySubject = new Map<string, Who>(apps.map((a) => [a.candidate.subjectRef, { name: a.candidate.user.name, appId: a.id }]));
  const titles = new Map(results.tasks.map((t) => [t.pattern_id, t.title]));
  const view = (w: Who) => `/recruiter/jobs/${jobId}/applicants/${w.appId}`;
  return (
    <div className="space-y-6">
      <AssessmentTotal assessment={results.assessment} titles={titles} who={(ref) => bySubject.get(ref)} view={view} />
      <section>
        <h2 className="font-semibold">Results by task</h2>
        <p className="mt-0.5 mb-4 text-sm text-muted">
          Each task on its own: hidden tests passed, then time taken; equal places are shared. Every applicant got the
          same tasks, each variant equally hard. Why a test failed is on the applicant&apos;s page.
        </p>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {results.tasks.map((t) => {
            const ranked = forApplicants(t.ranked, (r) => who.get(r.session_id));
            const pending = forApplicants(t.pending, (r) => who.get(r.session_id));
            return (
              <article key={t.pattern_id} className="rounded-2xl border border-line bg-panel p-5">
                <h3 className="mb-3 flex items-center gap-2 font-semibold"><Icon.Code className="size-4 text-accent" />{t.title}</h3>
                {ranked.length === 0 && <p className="text-sm text-muted">No final result yet.</p>}
                <ol className="space-y-2">
                  {ranked.map((r) => (
                    <li key={r.session_id} className="flex items-center gap-3 text-sm">
                      <Place rank={r.rank} />
                      <Link href={view(r.who)} className="min-w-0 flex-1 truncate font-medium hover:text-accent">{r.who.name}</Link>
                      <span className="flex w-28 items-center gap-2" title={`${r.core} core, ${r.twist} twist`}>
                        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-line"><span className="block h-full rounded-full bg-accent" style={{ width: `${r.total ? (r.passed / r.total) * 100 : 0}%` }} /></span>
                        <span className="text-xs tabular-nums">{r.passed}/{r.total}</span>
                      </span>
                      <span className="w-14 text-right text-xs text-muted tabular-nums">{Math.round(r.time_used_seconds / 60)} min</span>
                    </li>
                  ))}
                </ol>
                {pending.length > 0 && (
                  <p className="mt-3 border-t border-line pt-3 text-xs text-muted">
                    No result yet:{" "}
                    {pending.map((p, i) => (
                      <span key={p.session_id}>{i > 0 && "; "}<Link href={view(p.who)} className="underline">{p.who.name}</Link> ({pendingStatus(p, t.max_attempts)})</span>
                    ))}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function Place({ rank }: { rank: number }) {
  return (
    <span className={`grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold ${rank === 1 ? "bg-highlight/20 text-[#b45309] dark:text-highlight" : "bg-background text-muted ring-1 ring-line"}`}>
      {rank}
    </span>
  );
}

/** The whole assessment, the way an online test totals its questions: each task worth
 * the same points, summed over the job's tasks, then less time. Only someone who has
 * finished every task is ranked; the rest are listed with what they are waiting on. */
function AssessmentTotal({ assessment, titles, who, view }: {
  assessment: JobResults["assessment"]; titles: Map<string, string>;
  who: (ref: string) => Who | undefined; view: (w: Who) => string;
}) {
  if (!assessment.tasks.length) return null;
  const ranked = forApplicants(assessment.ranked, (r) => who(r.candidate_ref));
  const waiting = forApplicants(assessment.in_progress, (r) => who(r.candidate_ref));
  const name = (p: string) => titles.get(p) ?? p;
  return (
    <section className="rounded-2xl border border-line bg-panel p-5 sm:p-6">
      <h2 className="font-semibold">Assessment total</h2>
      <p className="mt-0.5 mb-4 text-sm text-muted">
        Each task is worth {assessment.points_per_task} points (its share of hidden tests passed), added up over{" "}
        {assessment.tasks.map(name).join(" and ")}; equal totals go to less time. A task that expired with nothing submitted scores 0.
      </p>
      {ranked.length === 0 && <p className="text-sm text-muted">Nobody has finished every task yet.</p>}
      {ranked.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="text-xs tracking-wide text-muted uppercase">
              <tr>
                <th className="py-2 pr-3 font-medium">#</th><th className="pr-3 font-medium">Applicant</th><th className="pr-3 font-medium">Total</th>
                {assessment.tasks.map((p) => <th key={p} className="pr-3 font-medium">{name(p)}</th>)}
                <th className="font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((r) => (
                <tr key={r.candidate_ref} className="border-t border-line">
                  <td className="py-2.5 pr-3"><Place rank={r.rank} /></td>
                  <td className="pr-3">
                    <Link href={view(r.who)} className="flex items-center gap-2.5 font-medium hover:text-accent"><Avatar name={r.who.name} />{r.who.name}</Link>
                  </td>
                  <td className="pr-3">
                    <span className="flex items-center gap-2">
                      <span className="h-2 w-20 overflow-hidden rounded-full bg-line"><span className="block h-full rounded-full bg-accent" style={{ width: `${r.out_of ? (r.points / r.out_of) * 100 : 0}%` }} /></span>
                      <span className="font-semibold tabular-nums">{r.points}<span className="font-normal text-muted">/{r.out_of}</span></span>
                    </span>
                  </td>
                  {r.per_task.map((t) => <td key={t.pattern_id} className="pr-3 tabular-nums">{t.points}</td>)}
                  <td className="text-muted tabular-nums">{Math.round(r.time_used_seconds / 60)} min</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {waiting.length > 0 && (
        <p className="mt-3 border-t border-line pt-3 text-sm text-muted">
          Still to finish:{" "}
          {waiting.map((w, i) => (
            <span key={w.candidate_ref}>{i > 0 && "; "}<Link href={view(w.who)} className="underline">{w.who.name}</Link> ({w.tasks.map(name).join(", ")})</span>
          ))}
        </p>
      )}
    </section>
  );
}
