"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { type ReactNode, startTransition, useActionState, useState } from "react";

import { finishTask, runExamples, submitSolution } from "@/app/candidate/actions";

import { Countdown } from "./candidate";
import { Icon } from "./icons";

const CodeEditor = dynamic(() => import("./code-editor"), {
  ssr: false,
  loading: () => <div className="h-full animate-pulse bg-[#1e1e1e]" />,
});

/** The task workspace: the problem beside an editor, a console under it, the clock and
 * the submissions above. Rendered in the browser only (see ide.tsx), because the code
 * starts from this browser's saved draft. Run tries the visible examples, as often as
 * wanted, never scored; Submit runs the hidden tests, one attempt of `maxAttempts`. */
export default function Workspace({ sessionId, title, meta, deadline, starter, attempt, maxAttempts, problem, history, last }: {
  sessionId: string; title: string; meta: string[]; deadline: string | null; starter: string;
  attempt: number; maxAttempts: number; // `attempt`: the next one
  problem: ReactNode; history: ReactNode | null; last: number; // `last`: the newest attempt made, 0 for none
}) {
  const key = `draft:${sessionId}`;
  const [code, setCode] = useState(() => {
    try {
      return localStorage.getItem(key) ?? starter;
    } catch {
      return starter;
    }
  });
  const [tab, setTab] = useState<"problem" | "attempts">("problem");
  const [shown, setShown] = useState<"run" | "submit" | null>(null);
  const [run, runAction, running] = useActionState(runExamples.bind(null, sessionId), undefined);
  const [sub, submitAction, submitting] = useActionState(submitSolution.bind(null, sessionId), undefined);
  const [fin, finishAction, finishing] = useActionState(finishTask.bind(null, sessionId), undefined);
  const busy = running || submitting || finishing;

  function edit(next: string) {
    setCode(next);
    try {
      localStorage.setItem(key, next);
    } catch {}
  }
  const form = () => {
    const f = new FormData();
    f.set("code", code);
    return f;
  };
  function doRun() {
    if (busy) return;
    setShown("run");
    startTransition(() => runAction(form()));
  }
  function doSubmit() {
    const final = attempt === maxAttempts;
    if (!confirm(`Submit attempt ${attempt} of ${maxAttempts}? The hidden tests run now.${final ? " This is your last attempt, so it becomes your result." : " Your last attempt counts."}`)) return;
    setShown("submit");
    startTransition(() => submitAction(form()));
  }
  function doFinish() {
    if (!confirm(`Finish now? Attempt ${last} becomes your result, and no more can be made.`)) return;
    startTransition(() => finishAction());
  }
  function reset() {
    if (confirm("Replace your code with the starter code?")) edit(starter);
  }

  return (
    <div className="flex flex-col lg:h-[calc(100dvh-56px)]">
      {/* Top bar: what, how long, how many submissions. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-panel px-4 py-2.5 sm:px-6">
        <Link href="/candidate/assessments" className="text-muted hover:text-accent" aria-label="All assessments">
          <Icon.Arrow className="size-4 rotate-180" />
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-semibold">{title}</h1>
          <p className="truncate text-xs text-muted">{meta.join(" · ")}</p>
        </div>
        <div className="flex items-center gap-1.5" title={`${attempt - 1} of ${maxAttempts} submissions used`}>
          <span className="mr-1 text-xs text-muted">Submissions</span>
          {Array.from({ length: maxAttempts }, (_, i) => (
            <span key={i} className={`size-2.5 rounded-full ${i < attempt - 1 ? "bg-accent" : "bg-line"}`} />
          ))}
        </div>
        {deadline && (
          <span className="flex items-center gap-1.5 rounded-lg bg-background px-2.5 py-1 text-sm font-semibold tabular-nums ring-1 ring-line">
            <Icon.Clock className="size-4 text-muted" /> <Countdown deadline={deadline} />
          </span>
        )}
        {last > 0 && (
          <button type="button" onClick={doFinish} disabled={busy}
            className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium transition hover:border-accent hover:text-accent disabled:opacity-60">
            {finishing ? "Finishing…" : "Finish now"}
          </button>
        )}
      </div>
      {fin?.message && <p className="bg-danger/10 px-6 py-2 text-sm text-danger">{fin.message}</p>}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(340px,40%)_1fr]">
        {/* The problem, and the submissions so far. */}
        <section className="flex min-h-0 flex-col border-line bg-panel lg:border-r">
          <div className="flex gap-1 border-b border-line px-4 sm:px-6">
            <Tab on={tab === "problem"} onClick={() => setTab("problem")}>Problem</Tab>
            {history && <Tab on={tab === "attempts"} onClick={() => setTab("attempts")}>Submissions ({attempt - 1})</Tab>}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">{tab === "problem" || !history ? problem : history}</div>
        </section>

        {/* The editor and its console. */}
        <section className="flex min-h-0 flex-col bg-[#1e1e1e] text-[#d4d4d4]">
          <div className="flex items-center justify-between border-b border-white/10 bg-[#252526] pr-2 text-sm">
            <span className="flex items-center gap-2 border-t-2 border-accent bg-[#1e1e1e] px-4 py-2 font-mono text-xs">
              <Icon.Code className="size-3.5 text-[#4ec9b0]" /> solution.py
            </span>
            <button type="button" onClick={reset} className="rounded px-2 py-1 text-xs text-white/60 transition hover:bg-white/10 hover:text-white">
              Reset to starter
            </button>
          </div>
          <div className="h-[55vh] min-h-0 lg:h-auto lg:flex-1">
            <CodeEditor value={code} onChange={edit} onRun={doRun} />
          </div>
          <Console shown={shown} run={run} sub={sub} running={running} submitting={submitting} />
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 bg-[#252526] px-4 py-2.5">
            <span className="hidden text-xs text-white/50 sm:block">Ctrl/⌘ + Enter runs the examples · drafts save in this browser</span>
            <div className="ml-auto flex gap-2">
              <button type="button" onClick={doRun} disabled={busy}
                className="flex items-center gap-1.5 rounded-lg bg-white/10 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/15 disabled:opacity-50">
                <Play /> {running ? "Running…" : "Run examples"}
              </button>
              <button type="button" onClick={doSubmit} disabled={busy}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition hover:brightness-110 disabled:opacity-50">
                {submitting ? "Submitting…" : `Submit ${attempt}/${maxAttempts}`}
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

type RunAnswer = Awaited<ReturnType<typeof runExamples>>;
type SubmitAnswer = Awaited<ReturnType<typeof submitSolution>>;

/** What the last Run or Submit said. Run's examples are visible tests, so their details
 * are the candidate's to see. */
function Console({ shown, run, sub, running, submitting }: {
  shown: "run" | "submit" | null; run: RunAnswer; sub: SubmitAnswer; running: boolean; submitting: boolean;
}) {
  const examples = run?.examples;
  const passed = examples?.examples.filter((x) => x.passed).length ?? 0;
  let body: ReactNode;
  if (running) body = <p className="text-white/60">Running the examples in the sandbox…</p>;
  else if (submitting) body = <p className="text-white/60">Running the hidden tests…</p>;
  else if (shown === "submit" && (sub?.message || sub?.errors)) {
    body = <pre className="whitespace-pre-wrap text-[#f48771]">{sub.message ?? Object.values(sub.errors ?? {}).flat().join("\n")}</pre>;
  } else if (shown === "run" && (run?.message || run?.errors)) {
    body = <pre className="whitespace-pre-wrap text-[#f48771]">{run.message ?? Object.values(run.errors ?? {}).flat().join("\n")}</pre>;
  } else if (shown === "run" && examples) {
    body = (
      <>
        <p className={`mb-2 font-semibold ${passed === examples.examples.length ? "text-[#89d185]" : "text-[#f48771]"}`}>
          {passed} of {examples.examples.length} examples passed <span className="font-normal text-white/50">· not scored</span>
        </p>
        {examples.note && <pre className="mb-2 whitespace-pre-wrap text-[#f48771]">{examples.note}</pre>}
        <ul className="space-y-1.5">
          {examples.examples.map((x) => (
            <li key={x.name}>
              <span className={x.passed ? "text-[#89d185]" : "text-[#f48771]"}>{x.passed ? "✓" : "✗"}</span>{" "}
              {x.name.replace(/^example_/, "").replaceAll("_", " ")}
              {x.detail && <pre className="mt-1 ml-4 whitespace-pre-wrap text-white/50">{x.detail}</pre>}
            </li>
          ))}
        </ul>
      </>
    );
  } else {
    body = <p className="text-white/40">Run your code to try it on the examples. Submitting runs the hidden tests.</p>;
  }
  return (
    <div className="h-48 shrink-0 overflow-y-auto border-t border-white/10 bg-[#181818] px-4 py-3 font-mono text-[13px]">
      <p className="mb-2 text-[11px] font-semibold tracking-wider text-white/40 uppercase">Console</p>
      {body}
    </div>
  );
}

function Tab({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on}
      className={`relative px-3 py-3 text-sm font-medium transition ${on ? "text-accent" : "text-muted hover:text-foreground"}`}>
      {children}
      {on && <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent" />}
    </button>
  );
}

function Play() {
  return <svg viewBox="0 0 24 24" className="size-3.5" fill="currentColor" aria-hidden><path d="M7 5v14l11-7z" /></svg>;
}
