import Link from "next/link";
import { after } from "next/server";
import { type ReactNode, Suspense } from "react";

import { BeginTask } from "@/components/candidate";
import { Chip, LinkButton } from "@/components/dashboard";
import { Icon } from "@/components/icons";
import { Workspace } from "@/components/ide";
import { Markdown } from "@/components/markdown";
import { myAssessment, requireCandidate, taskFor } from "@/lib/candidate";
import { call, ServiceError } from "@/lib/services";
import { skillLabels } from "@/lib/skills";
import { settleAssessment } from "@/lib/sync";
import { when } from "@/lib/tasks";
import type { Attempts, CandidateResult, Task } from "@/lib/types";

export default function AssessmentPage({ params }: PageProps<"/candidate/assessments/[id]">) {
  return (
    <Suspense fallback={<div className="mx-auto mt-8 h-96 w-full max-w-4xl animate-pulse rounded-2xl bg-line" />}>
      <Assessment params={params} />
    </Suspense>
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
    if (e instanceof ServiceError) return <Narrow><State icon="Clock" title="This assessment can't be loaded right now" text={e.message} /></Narrow>;
    throw e;
  }
  // Final by the deadline, with nobody pressing a button: settle it now.
  if (task.status === "submitted" && !row.sentToM6At) after(() => settleAssessment(row.id).catch(() => {}));
  const label = await skillLabels();
  const job = row.application?.job;
  const meta = [taskFor(job), label(task.skill), cap(task.level), `${task.time_limit_minutes} min`];

  if (task.status === "open" && task.starter !== null) {
    const last = attempts?.attempts.at(-1)?.attempt ?? 0;
    return (
      <Workspace
        sessionId={task.session_id} title={task.title} meta={meta} deadline={task.deadline} starter={task.starter}
        attempt={task.attempts_used + 1} maxAttempts={task.max_attempts} last={last}
        problem={<Problem task={task} />}
        history={attempts && attempts.attempts.length > 0 ? <History attempts={attempts} /> : null}
      />
    );
  }

  if (task.status === "issued") {
    return (
      <Narrow>
        <section className="rounded-2xl border border-line bg-panel p-6 sm:p-8">
          <div className="flex flex-wrap gap-2">
            <Chip tone="accent">{job ? `${job.org.name} · ${job.title}` : "Practice"}</Chip>
            <Chip>{label(task.skill)}</Chip>
            <Chip>{cap(task.level)}</Chip>
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight sm:text-3xl">{task.title}</h1>
          {task.start_by && (
            <p className="mt-2 flex items-center gap-1.5 text-sm text-muted"><Icon.Clock className="size-4" /> Start by {when(task.start_by)}</p>
          )}
          <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Fact icon="Clock" big={`${task.time_limit_minutes} min`} small="from when you press Start" />
            <Fact icon="Check" big={`${task.max_attempts} submissions`} small="your last one counts" />
            <Fact icon="Code" big="Python" small="run examples as often as you like" />
          </div>
          <p className="mt-6 text-sm text-muted">The problem appears when you start. Make sure you have {task.time_limit_minutes} uninterrupted minutes.</p>
          <div className="mt-4"><BeginTask sessionId={task.session_id} minutes={task.time_limit_minutes} /></div>
        </section>
      </Narrow>
    );
  }

  if (task.status === "expired" && !attempts?.attempts.length) {
    return (
      <Narrow>
        <State icon="Clock" title={`${task.title} has expired`}
          text={task.started_at ? "Time ran out before a submission arrived, so nothing was scored." : "The start-by date passed before it was started, so nothing was scored."}
          action={<LinkButton href="/candidate/assessments">Back to assessments</LinkButton>} />
      </Narrow>
    );
  }

  // Submitted (or expired after an attempt): the result.
  const counted = attempts?.attempts.find((a) => a.attempt === attempts.counted) ?? attempts?.attempts.at(-1);
  return (
    <Narrow>
      <Link href="/candidate/assessments" className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-accent">
        <Icon.Arrow className="size-4 rotate-180" /> All assessments
      </Link>
      {counted ? <ResultView task={task} meta={meta} result={counted} attempts={attempts!} skill={label(task.skill)} added={!!row.sentToM6At} />
        : <State icon="Check" title="Submitted" text="Your result is being prepared." />}
    </Narrow>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function Narrow({ children }: { children: ReactNode }) {
  return <main className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6">{children}</main>;
}

function Problem({ task }: { task: Task }) {
  return (
    <article className="space-y-6">
      <h2 className="text-xl font-bold tracking-tight">{task.title}</h2>
      {task.story && <Markdown>{task.story}</Markdown>}
      {task.requirements && (
        <div className="rounded-xl border border-line bg-background p-4">
          <p className="mb-2 text-xs font-semibold tracking-wider text-muted uppercase">Requirements</p>
          <Markdown>{task.requirements}</Markdown>
        </div>
      )}
    </article>
  );
}

const OUTCOME: Record<CandidateResult["outcome"], string> = {
  passed: "Every test passed",
  tests_failed: "Some tests failed",
  import_error: "The code couldn't be imported, so no test ran",
  timeout: "The run took longer than the sandbox allows",
  resource_limit: "The run used too much memory",
};

/** Submissions so far, newest first; tests by name only (the reasons quote hidden tests). */
function History({ attempts }: { attempts: Attempts }) {
  return (
    <ul className="space-y-3">
      {[...attempts.attempts].reverse().map((r) => (
        <li key={r.attempt} className="rounded-xl border border-line p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium">Submission {r.attempt}</p>
            {r.score && <span className="text-sm font-semibold tabular-nums">{r.score.passed}/{r.score.total} tests</span>}
          </div>
          {r.score && <Bar passed={r.score.passed} total={r.score.total} />}
          <p className="mt-2 text-sm text-muted">{OUTCOME[r.outcome]}</p>
          {r.note && <pre className="mt-2 text-xs whitespace-pre-wrap text-danger">{r.note}</pre>}
        </li>
      ))}
      <li className="text-xs text-muted">Failed tests are named, not explained: the reasons would reveal the hidden tests.</li>
    </ul>
  );
}

function ResultView({ task, meta, result, attempts, skill, added }: {
  task: Task; meta: string[]; result: CandidateResult; attempts: Attempts; skill: string; added: boolean;
}) {
  const s = result.score;
  const minutes = Math.max(1, Math.round(result.time_used_seconds / 60));
  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-line bg-panel p-6 sm:p-8">
        <p className="text-sm text-muted">{meta.join(" · ")}</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">{task.title}</h1>
        <div className="mt-6 flex flex-col gap-6 sm:flex-row sm:items-center">
          <Ring passed={s?.passed ?? 0} total={s?.total ?? 0} />
          <div className="flex-1 space-y-4">
            <p className={`text-lg font-semibold ${result.outcome === "passed" ? "text-ok" : ""}`}>{OUTCOME[result.outcome]}</p>
            {s && (
              <div className="space-y-3">
                <Group label="Core tests" passed={s.core_passed} total={s.core_total} />
                <Group label="Twist tests" passed={s.twist_passed} total={s.twist_total} />
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <Chip>{minutes} min used of {task.time_limit_minutes}</Chip>
              <Chip>Submission {result.attempt} of {attempts.max_attempts} counted</Chip>
            </div>
          </div>
        </div>
      </section>

      {result.tests.length > 0 && (
        <section className="rounded-2xl border border-line bg-panel p-5 sm:p-6">
          <h2 className="mb-4 font-semibold">Tests</h2>
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {result.tests.map((t) => (
              <li key={t.name} className="flex items-center gap-2.5 rounded-lg bg-background px-3 py-2 text-sm">
                <span className={`grid size-5 shrink-0 place-items-center rounded-full text-xs font-bold ${t.passed ? "bg-ok/15 text-ok" : "bg-danger/15 text-danger"}`}>
                  {t.passed ? "✓" : "✗"}
                </span>
                <span className="min-w-0 flex-1 truncate">{t.name.replaceAll("_", " ")}</span>
                <span className="text-xs text-muted">{t.group}</span>
              </li>
            ))}
          </ul>
          {result.note && <pre className="mt-3 text-xs whitespace-pre-wrap text-danger">{result.note}</pre>}
        </section>
      )}

      {attempts.attempts.length > 1 && (
        <section className="rounded-2xl border border-line bg-panel p-5 sm:p-6">
          <h2 className="mb-4 font-semibold">Your submissions</h2>
          <ul className="space-y-3">
            {attempts.attempts.map((r) => (
              <li key={r.attempt} className="grid grid-cols-[6.5rem_1fr_4rem] items-center gap-3 text-sm">
                <span className={r.attempt === result.attempt ? "font-semibold" : "text-muted"}>
                  Submission {r.attempt}
                </span>
                <Bar passed={r.score?.passed ?? 0} total={r.score?.total ?? 1} />
                <span className="text-right tabular-nums">{r.score ? `${r.score.passed}/${r.score.total}` : "–"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-accent/30 bg-accent/5 p-5">
        <p className="flex items-center gap-2 text-sm"><Icon.Spark className="size-5 text-accent" /> {added ? "This result now counts as evidence for" : "This result is being added as evidence for"} <strong>{skill}</strong>.</p>
        <LinkButton href={`/candidate/skills/${encodeURIComponent(task.skill)}`}>See my {skill} score</LinkButton>
      </section>
    </div>
  );
}

/** Tests passed, as the assessment module counts them: one ring, one fraction. */
function Ring({ passed, total }: { passed: number; total: number }) {
  const r = 15.5;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative size-36 shrink-0" role="img" aria-label={`${passed} of ${total} tests passed`}>
      <svg viewBox="0 0 36 36" className="size-full -rotate-90">
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="3.5" className="stroke-line" />
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="3.5" strokeLinecap="round" className="stroke-accent"
          strokeDasharray={`${total ? (passed / total) * c : 0} ${c}`} />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-center leading-none">
        <span><span className="block text-3xl font-bold">{passed}/{total}</span><span className="mt-1 block text-xs text-muted">tests passed</span></span>
      </span>
    </div>
  );
}

function Group({ label, passed, total }: { label: string; passed: number; total: number }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-sm"><span>{label}</span><span className="tabular-nums text-muted">{passed}/{total}</span></div>
      <Bar passed={passed} total={total} />
    </div>
  );
}

function Bar({ passed, total }: { passed: number; total: number }) {
  return (
    <span className="mt-2 block h-2 overflow-hidden rounded-full bg-line" aria-hidden>
      <span className="block h-full rounded-full bg-accent" style={{ width: `${total ? (passed / total) * 100 : 0}%` }} />
    </span>
  );
}

function Fact({ icon, big, small }: { icon: "Clock" | "Check" | "Code"; big: string; small: string }) {
  const Glyph = Icon[icon];
  return (
    <div className="rounded-xl bg-background p-4 ring-1 ring-line">
      <Glyph className="size-5 text-accent" />
      <p className="mt-2 font-semibold">{big}</p>
      <p className="text-sm text-muted">{small}</p>
    </div>
  );
}

function State({ icon, title, text, action }: { icon: "Clock" | "Check"; title: string; text: string; action?: ReactNode }) {
  const Glyph = Icon[icon];
  return (
    <section className="rounded-2xl border border-line bg-panel px-6 py-12 text-center">
      <span className="mx-auto grid size-14 place-items-center rounded-full bg-accent/10 text-accent"><Glyph className="size-7" /></span>
      <h1 className="mt-4 text-xl font-bold tracking-tight">{title}</h1>
      <p className="mx-auto mt-2 max-w-md text-muted">{text}</p>
      {action && <div className="mt-6">{action}</div>}
    </section>
  );
}
