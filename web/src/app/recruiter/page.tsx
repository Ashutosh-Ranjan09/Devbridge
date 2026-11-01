import { Suspense } from "react";

import { LinkButton } from "@/components/dashboard";
import { type JobRow, JobBoard } from "@/components/hiring";
import { db } from "@/lib/db";
import { requireRecruiter } from "@/lib/recruiter";
import { call } from "@/lib/services";
import { skillLabels } from "@/lib/skills";
import { day } from "@/lib/tasks";
import type { Job } from "@/lib/types";

export default function RecruiterHome() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-line" />}>
        <Jobs />
      </Suspense>
    </main>
  );
}

async function Jobs() {
  const me = await requireRecruiter();
  const jobs = await db.job.findMany({
    where: { orgId: { in: me.orgIds } },
    include: { org: true, applications: { select: { status: true } } },
    orderBy: { createdAt: "desc" },
  });
  // A module that is down leaves a job without its status and skills, not the page broken.
  const [details, label] = await Promise.all([
    Promise.all(jobs.map((j) => call<Job>("assess", `/v1/jobs/${encodeURIComponent(j.id)}`).catch(() => null))),
    skillLabels(),
  ]);
  const rows = jobs.map((j, i): JobRow => {
    const d = details[i];
    const count = (s: string) => j.applications.filter((a) => a.status === s).length;
    return {
      id: j.id, title: j.title, org: j.org.name, created: day(j.createdAt),
      state: !d ? "unknown" : d.status === "proposed" ? "draft" : j.open ? "listed" : "closed",
      must: d ? d.skills.filter((s) => s.skill_id && s.priority === "must").map((s) => label(s.skill_id as string)) : [],
      stages: { APPLIED: count("APPLIED"), ASSESSMENT_SENT: count("ASSESSMENT_SENT"), SUBMITTED: count("SUBMITTED"), DECIDED: count("DECIDED") },
    };
  });
  const all = jobs.flatMap((j) => j.applications);
  const tiles = [
    { label: "Listed roles", value: rows.filter((r) => r.state === "listed").length, hint: "Open to applications" },
    { label: "Drafts", value: rows.filter((r) => r.state === "draft").length, hint: "Skills to confirm" },
    { label: "Applicants", value: all.length, hint: "Across every job" },
    { label: "Waiting on you", value: all.filter((a) => a.status === "APPLIED" || a.status === "SUBMITTED").length, hint: "New, or tests to review", strong: true },
  ];

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Jobs</h1>
          <p className="mt-1 text-muted">
            Hiring for {me.orgs.map((o) => o.name).join(", ") || "no organisation yet"}
          </p>
        </div>
        <LinkButton href="/recruiter/jobs/new">+ New job</LinkButton>
      </div>
      <dl className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className={`rounded-2xl border p-4 sm:p-5 ${t.strong && t.value ? "border-accent/40 bg-accent/5" : "border-line bg-panel"}`}>
            <dt className="text-sm text-muted">{t.label}</dt>
            <dd className={`mt-1 text-3xl font-bold tabular-nums ${t.strong && t.value ? "text-accent" : ""}`}>{t.value}</dd>
            <dd className="mt-0.5 text-xs text-muted">{t.hint}</dd>
          </div>
        ))}
      </dl>
      <JobBoard jobs={rows} />
    </>
  );
}
