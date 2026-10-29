import { after } from "next/server";
import { Suspense } from "react";

import { Countdown, Editor } from "@/components/candidate";
import { Markdown } from "@/components/markdown";
import { Card, Loading, Page } from "@/components/ui";
import { myAssessment, requireCandidate } from "@/lib/candidate";
import { call, ServiceError } from "@/lib/services";
import { forwardAssessment } from "@/lib/sync";
import type { CandidateResult, Task } from "@/lib/types";

export default function AssessmentPage({ params }: PageProps<"/candidate/assessments/[id]">) {
  return (
    <Page title="Assessment">
      <Suspense fallback={<Loading />}>
        <Assessment params={params} />
      </Suspense>
    </Page>
  );
}

async function Assessment({ params }: { params: Promise<{ id: string }> }) {
  const me = await requireCandidate();
  const row = await myAssessment(me.id, (await params).id);
  let task: Task;
  let result: CandidateResult | null = null;
  try {
    task = await call<Task>("assess", `/v1/sessions/${encodeURIComponent(row.id)}`);
    if (task.status === "submitted") {
      // The candidate view only (the default). `view=full` quotes the hidden tests.
      result = await call<CandidateResult>("assess", `/v1/sessions/${encodeURIComponent(row.id)}/result`);
    }
  } catch (e) {
    if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
    throw e;
  }
  if (result && !row.sentToM6At) after(() => forwardAssessment(row.id).catch(() => {}));

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">{task.title}</h2>
          {task.status === "open" && <Countdown deadline={task.deadline} />}
        </div>
        <p className="mb-3 text-sm text-muted">{task.skill} · {task.level} · {task.time_limit_minutes} minutes</p>
        <Markdown>{task.story}</Markdown>
        <div className="mt-4"><Markdown>{task.requirements}</Markdown></div>
      </Card>
      {task.status === "open" && <Card><Editor sessionId={task.session_id} starter={task.starter} /></Card>}
      {task.status === "expired" && <Card><p>The deadline passed before a submission arrived, so nothing was scored.</p></Card>}
      {result && <Result result={result} />}
    </div>
  );
}

const OUTCOME: Record<CandidateResult["outcome"], string> = {
  passed: "Every test passed.",
  tests_failed: "Some tests failed.",
  import_error: "The code could not be imported, so no test ran.",
  timeout: "The whole run took longer than the sandbox allows.",
  resource_limit: "The run was stopped for using too much memory.",
};

function Result({ result }: { result: CandidateResult }) {
  const s = result.score;
  return (
    <Card>
      <h2 className="mb-1 font-semibold">Result</h2>
      <p>{OUTCOME[result.outcome]}</p>
      {s && (
        <p className="mt-1 text-sm text-muted">
          {s.passed} of {s.total} tests passed ({s.core_passed}/{s.core_total} core, {s.twist_passed}/{s.twist_total} twist)
          · {Math.round(result.time_used_seconds / 60)} min used
        </p>
      )}
      {result.note && <p className="mt-2 font-mono text-sm">{result.note}</p>}
      <ul className="mt-3 space-y-1 text-sm">
        {result.tests.map((t) => (
          <li key={t.name}>
            <span className={t.passed ? "text-ok" : "text-danger"}>{t.passed ? "✓" : "✗"}</span>{" "}
            <code>{t.name.replaceAll("_", " ")}</code> <span className="text-muted">({t.group})</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">
        Which tests failed, not why: the reasons quote the hidden tests. A recruiter reading your result sees them.
      </p>
    </Card>
  );
}
