import { after } from "next/server";
import { Suspense } from "react";

import { BeginTask, Countdown, Editor, FinishTask } from "@/components/candidate";
import { Markdown } from "@/components/markdown";
import { Card, Loading, Page } from "@/components/ui";
import { myAssessment, requireCandidate, taskFor } from "@/lib/candidate";
import { call, ServiceError } from "@/lib/services";
import { settleAssessment } from "@/lib/sync";
import { when } from "@/lib/tasks";
import type { Attempts, CandidateResult, Task } from "@/lib/types";

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
  let attempts: Attempts | null = null;
  try {
    task = await call<Task>("assess", `/v1/sessions/${encodeURIComponent(row.id)}`);
    if (task.attempts_used > 0) {
      // The candidate view only (the default). `view=full` quotes the hidden tests.
      attempts = await call<Attempts>("assess", `/v1/sessions/${encodeURIComponent(row.id)}/attempts`);
    }
  } catch (e) {
    if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
    throw e;
  }
  // Final by the deadline, with nobody pressing a button: settle it now.
  if (task.status === "submitted" && !row.sentToM6At) after(() => settleAssessment(row.id).catch(() => {}));
  const last = attempts?.attempts.at(-1)?.attempt ?? 0;

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">{task.title}</h2>
          {task.status === "open" && task.deadline && <Countdown deadline={task.deadline} />}
        </div>
        <p className="mb-3 text-sm text-muted">
          For {taskFor(row.application?.job)} · {task.skill} · {task.level} · {task.time_limit_minutes} minutes
        </p>
        {task.story && <Markdown>{task.story}</Markdown>}
        {task.requirements && <div className="mt-4"><Markdown>{task.requirements}</Markdown></div>}
        {task.status === "issued" && (
          <div className="space-y-3">
            <p className="text-sm">
              {task.start_by && <>Start by <strong>{when(task.start_by)}</strong>. </>}
              The task is shown and the clock starts when you press Start: you will have {task.time_limit_minutes} minutes
              and one submission.
            </p>
            <BeginTask sessionId={task.session_id} minutes={task.time_limit_minutes} />
          </div>
        )}
      </Card>
      {task.status === "open" && task.starter !== null && (
        <Card>
          <Editor sessionId={task.session_id} starter={task.starter}
            attempt={task.attempts_used + 1} maxAttempts={task.max_attempts} />
        </Card>
      )}
      {task.status === "open" && last > 0 && <Card><FinishTask sessionId={task.session_id} attempt={last} /></Card>}
      {task.status === "expired" && (
        <Card>
          <p>
            {task.started_at
              ? "The deadline passed before a submission arrived, so nothing was scored."
              : "The start-by date passed before the task was started, so nothing was scored."}
          </p>
        </Card>
      )}
      {attempts && <AttemptList attempts={attempts} final={task.status === "submitted"} />}
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

/** Every attempt, newest first; once final, the counted one (the last) is marked. */
function AttemptList({ attempts, final }: { attempts: Attempts; final: boolean }) {
  return (
    <Card>
      <h2 className="mb-1 font-semibold">{final ? "Result" : "Your attempts"}</h2>
      <p className="text-sm text-muted">
        {final
          ? `Attempt ${attempts.counted} counts: your last.`
          : `${attempts.attempts.length} of ${attempts.max_attempts} used. Your last attempt counts.`}
      </p>
      <div className="mt-3 space-y-4">
        {[...attempts.attempts].reverse().map((r) => <Result key={r.attempt} result={r} counted={r.attempt === attempts.counted} />)}
      </div>
      <p className="mt-3 text-xs text-muted">
        Which tests failed, not why: the reasons quote the hidden tests. A recruiter reading your result sees them.
      </p>
    </Card>
  );
}

function Result({ result, counted }: { result: CandidateResult; counted: boolean }) {
  const s = result.score;
  return (
    <section>
      <h3 className="font-medium">
        Attempt {result.attempt} {counted && <span className="text-sm font-normal text-ok">counts</span>}
      </h3>
      <p>{OUTCOME[result.outcome]}</p>
      {s && (
        <p className="mt-1 text-sm text-muted">
          {s.passed} of {s.total} tests passed ({s.core_passed}/{s.core_total} core, {s.twist_passed}/{s.twist_total} twist)
          · {Math.round(result.time_used_seconds / 60)} min used
        </p>
      )}
      {result.note && <p className="mt-2 font-mono text-sm">{result.note}</p>}
      <ul className="mt-2 space-y-1 text-sm">
        {result.tests.map((t) => (
          <li key={t.name}>
            <span className={t.passed ? "text-ok" : "text-danger"}>{t.passed ? "✓" : "✗"}</span>{" "}
            <code>{t.name.replaceAll("_", " ")}</code> <span className="text-muted">({t.group})</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
