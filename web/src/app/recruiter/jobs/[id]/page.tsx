import Link from "next/link";
import { Suspense } from "react";

import { Musts } from "@/components/musts";
import { ActionButton } from "@/components/action-button";
import { SkillEditor } from "@/components/recruiter";
import { Card, Loading, Page } from "@/components/ui";
import { confirmJob, setOpen } from "@/app/recruiter/actions";
import { db } from "@/lib/db";
import { myJob, requireRecruiter } from "@/lib/recruiter";
import { call, ServiceError } from "@/lib/services";
import type { Job, JobTasks, Requirements, Shortlist, ShortlistEntry } from "@/lib/types";

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
    <Card>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">Applicants ({apps.length})</h3>
        <Link href={only ? "?" : "?only=clear"} className="text-sm text-accent underline">
          {only ? "Show everyone" : "Only those who clear every bar"}
        </Link>
      </div>
      <p className="mb-3 text-xs text-muted">Ordered by name. {shortlist.note} Match: {shortlist.match}.</p>
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
              </div>
              <Musts entry={entry} skills={skills} />
            </li>
          );
        })}
      </ul>
    </Card>
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
