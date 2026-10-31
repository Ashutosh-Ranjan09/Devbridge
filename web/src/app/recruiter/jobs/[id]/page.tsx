import Link from "next/link";
import { after } from "next/server";
import { Suspense } from "react";

import { Musts } from "@/components/musts";
import { ActionButton } from "@/components/action-button";
import { SkillEditor } from "@/components/recruiter";
import { Card, Loading, Page } from "@/components/ui";
import { confirmJob, setOpen } from "@/app/recruiter/actions";
import { db } from "@/lib/db";
import { myJob, requireRecruiter } from "@/lib/recruiter";
import { call, ServiceError } from "@/lib/services";
import { settleAssessment } from "@/lib/sync";
import { basisText, matchText } from "@/lib/match";
import { forApplicants, pendingStatus } from "@/lib/tasks";
import type { Job, JobResults, JobTasks, Requirements, Shortlist, ShortlistEntry } from "@/lib/types";

export default function JobPage({ params, searchParams }: PageProps<"/recruiter/jobs/[id]">) {
  return (
    <Page title="Job">
      <Suspense fallback={<Loading />}>
        <JobView params={params} searchParams={searchParams} />
      </Suspense>
    </Page>
  );
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
    if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
    throw e;
  }
  const head = (
    <div className="mb-4">
      <h2 className="text-xl font-semibold">{row.title}</h2>
      <p className="text-sm text-muted">
        {row.org.name} · skills {job.status === "confirmed" ? `confirmed by ${job.confirmed_by}` : `proposed by ${job.extracted_by === "rules" ? "rules" : job.extracted_by}`}
        {job.dropped_unquoted > 0 && ` · ${job.dropped_unquoted} proposed skill(s) dropped: their quote is not in the text`}
      </p>
    </div>
  );

  if (job.status === "proposed") {
    const catalogue = await call<{ skills: { skill_id: string }[] }>("m6", "/skills").then(
      (r) => r.skills.map((s) => s.skill_id), () => [],
    );
    return (
      <div className="space-y-4">
        {head}
        <Card><SkillEditor jobId={row.id} skills={job.skills} catalogue={catalogue} tasks={tasks} /></Card>
        <Card>
          <ActionButton action={confirmJob.bind(null, row.id)} label="Confirm these skills and tasks"
            note="Confirming locks them: a confirmed job is never edited." />
        </Card>
      </div>
    );
  }

  const must = job.skills.filter((s) => s.skill_id && s.priority === "must");
  const nice = job.skills.filter((s) => s.skill_id && s.priority === "nice");
  return (
    <div className="space-y-4">
      {head}
      <Card>
        <h3 className="mb-2 font-semibold">Must-haves</h3>
        <ul className="space-y-1 text-sm">
          {must.map((s) => (
            <li key={s.skill_id}>
              <code>{s.skill_id}</code>{" "}
              <span className="text-muted">
                {s.bar === null ? "assessed, not filtered" : s.bar === 0 ? "any direct evidence" : `bar ${s.bar.toFixed(2)}`}
              </span>
            </li>
          ))}
        </ul>
        {nice.length > 0 && <p className="mt-2 text-sm">Nice to have: {nice.map((s) => s.skill_id).join(", ")}</p>}
        <TasksSummary tasks={tasks} />
        <div className="mt-4">
          <ActionButton action={setOpen.bind(null, row.id, !row.open)} label={row.open ? "Close applications" : "Open for applications"}
            note={row.open ? "Candidates can see and apply to it." : "Not listed for candidates."} />
        </div>
      </Card>
      <Applicants jobId={row.id} skills={must.map((s) => s.skill_id as string)} only={(await searchParams).only === "clear"} />
    </div>
  );
}

async function Applicants({ jobId, skills, only }: { jobId: string; skills: string[]; only: boolean }) {
  const apps = await db.application.findMany({
    where: { jobId },
    include: { candidate: { include: { user: true } }, decision: true },
  });
  // By name: a list of people, never ordered by any skill.
  apps.sort((a, b) => a.candidate.user.name.localeCompare(b.candidate.user.name));
  if (!apps.length) return <Card><p className="text-sm text-muted">No applicants yet.</p></Card>;

  let shortlist: Shortlist;
  try {
    const requirements = await call<Requirements>("assess", `/v1/jobs/${encodeURIComponent(jobId)}/requirements`);
    const subjects = apps.map((a) => `subject=${encodeURIComponent(a.candidate.subjectRef)}`).join("&");
    shortlist = await call<Shortlist>("m6", `/shortlist?${subjects}`, { body: requirements });
  } catch (e) {
    if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
    throw e;
  }
  const entries = new Map<string, ShortlistEntry & { clearsAll: boolean }>([
    ...shortlist.candidates.map((c) => [c.subject_ref, { ...c, clearsAll: true }] as const),
    ...shortlist.others.map((c) => [c.subject_ref, { ...c, clearsAll: false }] as const),
  ]);
  const shown = only ? apps.filter((a) => entries.get(a.candidate.subjectRef)?.clearsAll) : apps;
  return (
    <>
    <ResultsByTask jobId={jobId} apps={apps} />
    <Card>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">Applicants ({apps.length})</h3>
        <Link href={only ? "?" : "?only=clear"} className="text-sm text-accent underline">
          {only ? "Show everyone" : "Only those who clear every bar"}
        </Link>
      </div>
      <p className="mb-3 text-xs text-muted">
        Ordered by name. {shortlist.note} Clears every bar: {shortlist.match}. {basisText(shortlist.job_match_basis)}
      </p>
      <ul className="space-y-3">
        {shown.map((a) => {
          const entry = entries.get(a.candidate.subjectRef) ?? null;
          return (
            <li key={a.id} className="border-t border-line pt-2">
              <div className="flex flex-wrap gap-x-3">
                <Link href={`/recruiter/jobs/${jobId}/applicants/${a.id}`} className="text-accent underline">{a.candidate.user.name}</Link>
                {a.decision
                  ? <span className="text-sm">decided: {a.decision.outcome.toLowerCase()}</span>
                  : <span className="text-sm text-muted">{a.status.toLowerCase().replace("_", " ")}</span>}
                <span className="text-sm text-muted">
                  {entry ? (entry.clearsAll ? "clears every bar" : "does not clear every bar") : "no evidence on record"}
                </span>
                {entry?.job_match && <span className="text-sm">job match {matchText(entry.job_match)}</span>}
              </div>
              <Musts entry={entry} skills={skills} />
            </li>
          );
        })}
      </ul>
    </Card>
    </>
  );
}

/** The tasks every applicant gets, as confirmed. */
function TasksSummary({ tasks }: { tasks: JobTasks }) {
  const chosen = Object.values(tasks.must).flat().filter((o) => o.chosen);
  const minutes = chosen.reduce((sum, o) => sum + o.time_limit_minutes, 0);
  return (
    <p className="mt-2 text-sm">
      Tasks every applicant gets:{" "}
      {chosen.length ? `${chosen.map((o) => o.title).join(", ")} (${minutes} minutes in all)` : "none"}
    </p>
  );
}

type Who = { name: string; appId: string };

/** Each task's results ranked on its own, as the assessment module ranks them: hidden
 * tests passed, then time taken. Never summed across tasks. The applicant rows below stay
 * in name order; a person picks from here and decides on the applicant's page. */
async function ResultsByTask({ jobId, apps }: {
  jobId: string; apps: { id: string; candidate: { subjectRef: string; user: { name: string } } }[];
}) {
  const sessions = await db.assessment.findMany({ where: { applicationId: { in: apps.map((a) => a.id) } } });
  if (!sessions.length) return null;
  const names = new Map(apps.map((a) => [a.id, a.candidate.user.name]));
  const who = new Map<string, Who>(sessions.map((s) => [s.id, { name: names.get(s.applicationId ?? "") ?? "?", appId: s.applicationId ?? "" }]));
  const bySubject = new Map<string, Who>(apps.map((a) => [a.candidate.subjectRef, { name: a.candidate.user.name, appId: a.id }]));
  let answer: JobResults;
  try {
    answer = await call<JobResults>("assess", `/v1/jobs/${encodeURIComponent(jobId)}/results`);
  } catch (e) {
    if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
    throw e;
  }
  const results = answer.tasks;
  const titles = new Map(results.map((t) => [t.pattern_id, t.title]));
  // Settled by the deadline with nobody pressing a button: tell M6 and the application.
  const settled = new Set(results.flatMap((t) => t.ranked.map((r) => r.session_id)));
  for (const s of sessions) if (settled.has(s.id) && !s.sentToM6At) after(() => settleAssessment(s.id).catch(() => {}));
  const view = (w: Who) => `/recruiter/jobs/${jobId}/applicants/${w.appId}`;
  return (
    <>
    <AssessmentTotal assessment={answer.assessment} titles={titles} who={(ref) => bySubject.get(ref)} view={view} />
    <Card>
      <h3 className="mb-1 font-semibold">Results by task</h3>
      <p className="mb-3 text-xs text-muted">
        Each task on its own: hidden tests passed, then time taken; equal places are shared. Every applicant got
        the same tasks, each variant equally hard. Why a test failed is on the applicant&apos;s page.
      </p>
      <div className="space-y-5">
        {results.map((t) => {
          const ranked = forApplicants(t.ranked, (r) => who.get(r.session_id));
          const pending = forApplicants(t.pending, (r) => who.get(r.session_id));
          return (
            <section key={t.pattern_id}>
              <h4 className="font-medium">{t.title}</h4>
              {ranked.length === 0 && <p className="text-sm text-muted">No final result yet.</p>}
              {ranked.length > 0 && (
                <table className="mt-1 w-full text-left text-sm">
                  <thead className="text-muted">
                    <tr><th className="py-1 pr-2">#</th><th className="pr-2">Applicant</th><th className="pr-2">Hidden tests</th><th className="pr-2">Time</th><th>Attempt</th></tr>
                  </thead>
                  <tbody>
                    {ranked.map((r) => (
                      <tr key={r.session_id} className="border-t border-line">
                        <td className="py-1 pr-2 font-mono">{r.rank}</td>
                        <td className="pr-2"><Link href={view(r.who)} className="text-accent underline">{r.who.name}</Link></td>
                        <td className="pr-2">{r.passed} of {r.total} <span className="text-muted">({r.core} core, {r.twist} twist)</span></td>
                        <td className="pr-2">{Math.round(r.time_used_seconds / 60)} min</td>
                        <td>{r.attempt} counts</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {pending.length > 0 && (
                <p className="mt-1 text-sm text-muted">
                  No result yet:{" "}
                  {pending.map((p, i) => (
                    <span key={p.session_id}>
                      {i > 0 && "; "}
                      <Link href={view(p.who)} className="underline">{p.who.name}</Link>{" "}
                      ({pendingStatus(p, t.max_attempts)})
                    </span>
                  ))}
                </p>
              )}
            </section>
          );
        })}
      </div>
    </Card>
    </>
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
    <Card>
      <h3 className="mb-1 font-semibold">Assessment total</h3>
      <p className="mb-3 text-xs text-muted">
        Each task is worth {assessment.points_per_task} points (its share of hidden tests passed), added up over{" "}
        {assessment.tasks.map(name).join(" and ")}; equal totals go to less time taken. A task that expired with
        nothing submitted scores 0.
      </p>
      {ranked.length === 0 && <p className="text-sm text-muted">Nobody has finished every task yet.</p>}
      {ranked.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-muted">
            <tr>
              <th className="py-1 pr-2">#</th><th className="pr-2">Applicant</th><th className="pr-2">Total</th>
              {assessment.tasks.map((p) => <th key={p} className="pr-2">{name(p)}</th>)}
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((r) => (
              <tr key={r.candidate_ref} className="border-t border-line">
                <td className="py-1 pr-2 font-mono">{r.rank}</td>
                <td className="pr-2"><Link href={view(r.who)} className="text-accent underline">{r.who.name}</Link></td>
                <td className="pr-2 font-medium">{r.points} / {r.out_of}</td>
                {r.per_task.map((t) => <td key={t.pattern_id} className="pr-2">{t.points}</td>)}
                <td>{Math.round(r.time_used_seconds / 60)} min</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {waiting.length > 0 && (
        <p className="mt-2 text-sm text-muted">
          Still to finish:{" "}
          {waiting.map((w, i) => (
            <span key={w.candidate_ref}>
              {i > 0 && "; "}
              <Link href={view(w.who)} className="underline">{w.who.name}</Link> ({w.tasks.map(name).join(", ")})
            </span>
          ))}
        </p>
      )}
    </Card>
  );
}
