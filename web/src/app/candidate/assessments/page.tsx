import Link from "next/link";
import { Suspense } from "react";

import { StartPractice } from "@/components/candidate";
import { Card, Loading, Page } from "@/components/ui";
import { requireCandidate } from "@/lib/candidate";
import { db } from "@/lib/db";
import { call, ServiceError } from "@/lib/services";
import type { Pattern, Task } from "@/lib/types";

export default function AssessmentsPage() {
  return (
    <Page title="Assessments">
      <Suspense fallback={<Loading />}>
        <Assessments />
      </Suspense>
    </Page>
  );
}

async function Assessments() {
  const me = await requireCandidate();
  const rows = await db.assessment.findMany({ where: { candidateId: me.id }, orderBy: { createdAt: "desc" } });
  let patterns: Pattern[];
  let tasks: (Task | null)[];
  try {
    [patterns, tasks] = await Promise.all([
      call<Pattern[]>("assess", "/v1/patterns"),
      Promise.all(rows.map((r) => call<Task>("assess", `/v1/sessions/${encodeURIComponent(r.id)}`).catch(() => null))),
    ]);
  } catch (e) {
    if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
    throw e;
  }
  return (
    <div className="space-y-4">
      {rows.length > 0 && (
        <Card>
          <h2 className="mb-2 font-semibold">Yours</h2>
          <ul className="space-y-1">
            {rows.map((r, i) => (
              <li key={r.id} className="flex flex-wrap gap-x-3">
                <Link href={`/candidate/assessments/${r.id}`} className="text-accent underline">
                  {tasks[i]?.title ?? r.id}
                </Link>
                <span className="text-sm text-muted">{tasks[i]?.status ?? "unavailable"}</span>
                <span className="text-sm text-muted">{r.applicationId ? "for a job" : "practice"}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card>
        <h2 className="mb-1 font-semibold">Practice</h2>
        <p className="mb-3 text-sm text-muted">
          Your own variant of the task, as hard as everyone else&apos;s. The clock starts when you press Start,
          you get one submission, and the result is added to your skill graph.
        </p>
        <ul className="space-y-3">
          {patterns.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="font-medium">{p.title}</p>
                <p className="text-sm text-muted">{p.skill} · {p.level} · {p.time_limit_minutes} minutes</p>
              </div>
              <StartPractice patternId={p.id} />
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
