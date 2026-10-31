import Link from "next/link";
import { Suspense } from "react";

import { Interval } from "@/components/interval";
import { Musts } from "@/components/musts";
import { DecisionForm, SendAssessment } from "@/components/recruiter";
import { CandidateNote, ReportView } from "@/components/report";
import { Card, Loading, Page } from "@/components/ui";
import { db } from "@/lib/db";
import { myApplication, requireRecruiter } from "@/lib/recruiter";
import { alsoChecked, m5Rules } from "@/lib/m5";
import { marksFor } from "@/lib/review";
import { START_BY_MAX_DAYS } from "@/lib/definitions";
import { dayIn, taskStatus } from "@/lib/tasks";
import { call, ServiceError } from "@/lib/services";
import type { FullResult, Profile, Report, Requirements, Running, Shortlist, Task } from "@/lib/types";

export default function ApplicantPage({ params }: PageProps<"/recruiter/jobs/[id]/applicants/[appId]">) {
  return (
    <Page title="Applicant">
      <Suspense fallback={<Loading />}>
        <Applicant params={params} />
      </Suspense>
    </Page>
  );
}

/** What the person deciding reads: the must-haves as M6 answers them, the skill profile,
 * the CV report, the job's assessment results in full — and the decision, which is theirs. */
async function Applicant({ params }: { params: Promise<{ id: string; appId: string }> }) {
  const me = await requireRecruiter();
  const { id: jobId, appId } = await params;
  const app = await myApplication(me.orgIds, jobId, appId);
  const ref = app.candidate.subjectRef;
  const [latest, assessments] = await Promise.all([
    db.verification.findFirst({ where: { candidateId: app.candidateId }, orderBy: { createdAt: "desc" } }),
    db.assessment.findMany({ where: { applicationId: app.id }, orderBy: { createdAt: "asc" } }),
  ]);

  const quiet = <T,>(p: Promise<T>) => p.catch((e: unknown) => (e instanceof ServiceError ? e : Promise.reject(e)));
  const [requirements, profile, report, marks, rules, tasks] = await Promise.all([
    quiet(call<Requirements>("assess", `/v1/jobs/${encodeURIComponent(jobId)}/requirements`)),
    quiet(call<Profile>("m6", `/developers/${encodeURIComponent(ref)}/profile`)),
    latest ? quiet(call<Report | Running>("m5", `/v1/verifications/${encodeURIComponent(latest.id)}`)) : null,
    latest ? marksFor(latest.id) : undefined,
    latest ? m5Rules() : null,
    Promise.all(assessments.map(async (a) => {
      const task = await call<Task>("assess", `/v1/sessions/${encodeURIComponent(a.id)}`).catch(() => null);
      // The full view: this is the person reading results, for their own job.
      const result = task?.status === "submitted"
        ? await call<FullResult>("assess", `/v1/sessions/${encodeURIComponent(a.id)}/result?view=full`).catch(() => null)
        : null;
      return { id: a.id, task, result };
    })),
  ]);
  const shortlist = requirements instanceof ServiceError ? null
    : await quiet(call<Shortlist>("m6", `/shortlist?subject=${encodeURIComponent(ref)}`, { body: requirements }));
  const entry = shortlist && !(shortlist instanceof ServiceError)
    ? [...shortlist.candidates, ...shortlist.others].find((c) => c.subject_ref === ref) ?? null : null;
  const musts = requirements instanceof ServiceError ? [] : requirements.must.map((m) => m.skill_id);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">{app.candidate.user.name}</h2>
        <p className="text-sm text-muted">
          {app.candidate.user.email} · applied to <Link href={`/recruiter/jobs/${jobId}`} className="underline">{app.job.title}</Link>{" "}
          {app.createdAt.toLocaleDateString("en-IN")} · {app.status.toLowerCase().replace("_", " ")}
        </p>
      </div>

      <Card>
        <h3 className="mb-2 font-semibold">Must-haves</h3>
        {shortlist instanceof ServiceError ? <p>{shortlist.message}</p> : <Musts entry={entry} skills={musts} />}
      </Card>

      <Card>
        <h3 className="mb-2 font-semibold">Assessment for this job</h3>
        {tasks.length === 0 && <p className="mb-3 text-sm text-muted">None sent yet.</p>}
        {tasks.map(({ id, task, result }) => (
          <div key={id} className="mb-4">
            <p className="font-medium">{task?.title ?? id} <span className="text-sm text-muted">{taskStatus(task)}</span></p>
            {result && (
              <>
                <p className="text-sm">
                  {result.outcome.replace("_", " ")}
                  {result.score && ` · ${result.score.passed} of ${result.score.total} tests passed (${result.score.core_passed}/${result.score.core_total} core, ${result.score.twist_passed}/${result.score.twist_total} twist)`}
                  {` · ${Math.round(result.time_used_seconds / 60)} min of ${task?.time_limit_minutes ?? "?"}`}
                </p>
                {result.note && <p className="font-mono text-sm">{result.note}</p>}
                <ul className="mt-1 text-sm">
                  {result.tests.map((t) => (
                    <li key={t.name}>
                      <span className={t.passed ? "text-ok" : "text-danger"}>{t.passed ? "✓" : "✗"}</span> <code>{t.name}</code>
                      {t.detail && <span className="block pl-5 font-mono text-xs text-muted">{t.detail}</span>}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        ))}
        {!app.decision && (
          <SendAssessment jobId={jobId} applicationId={app.id} sent={tasks.length > 0}
            startBy={{ default: dayIn(7), min: dayIn(0), max: dayIn(START_BY_MAX_DAYS - 1) }} />
        )}
      </Card>

      <Card>
        <h3 className="mb-2 font-semibold">Skills</h3>
        {profile instanceof ServiceError ? (
          <p className="text-sm text-muted">{profile.status === 404 ? "No evidence on record." : profile.message}</p>
        ) : (
          <ul className="space-y-2">
            {[...profile.skills].sort((a, b) => a.skill_id.localeCompare(b.skill_id)).map((s) => (
              <li key={s.skill_id} className="grid gap-1 sm:grid-cols-[10rem_auto_1fr] sm:items-center sm:gap-4">
                <code>{s.skill_id}</code>
                <Interval interval={s.interval} mean={s.mean} />
                <span className="text-sm text-muted">{s.evidence_count} evidence{s.inferred ? " · inferred" : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div>
        <h3 className="mb-2 font-semibold">CV report</h3>
        {!report ? <Card><p className="text-sm text-muted">No CV checked.</p></Card>
          : report instanceof ServiceError ? <Card><p>{report.message}</p></Card>
          : report.status === "running" ? <Card><p>Still being checked.</p></Card>
          : report.status === "failed" ? <Card><p>Could not be checked: {report.failure}</p></Card>
          : <div className="space-y-4">
              <CandidateNote note={latest?.note ?? null} />
              <ReportView report={report} marks={marks} alsoChecked={alsoChecked(report, rules)} />
            </div>}
      </div>

      <Card>
        <h3 className="mb-2 font-semibold">Decision</h3>
        {app.decision ? (
          <p>
            {app.decision.outcome.toLowerCase()} by {app.decision.decidedBy.name},{" "}
            {app.decision.createdAt.toLocaleString("en-IN")}: <q>{app.decision.reason}</q>
          </p>
        ) : (
          <DecisionForm jobId={jobId} applicationId={app.id} />
        )}
      </Card>
    </div>
  );
}
