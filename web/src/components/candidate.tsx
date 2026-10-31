"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useRef, useState } from "react";

import { beginTask, finishTask, runExamples, startPractice, submitSolution, uploadCv } from "@/app/candidate/actions";

import { Button, Field } from "./ui";

const PLATFORMS = [["github", "GitHub"], ["codeforces", "Codeforces"], ["leetcode", "LeetCode"], ["codechef", "CodeChef"]] as const;

/** `saved`: the handles typed last time. A refused upload shows what was typed instead;
 * the file itself must be chosen again (a browser never refills a file input). */
export function UploadCv({ saved }: { saved: Record<string, string> }) {
  const [state, action, pending] = useActionState(uploadCv, undefined);
  const value = (k: string) => state?.values?.[k] ?? saved[k];
  return (
    <form action={action} className="space-y-3">
      <input type="file" name="cv" accept=".pdf,.docx" className="block w-full text-sm" />
      {state?.errors?.cv?.map((e) => <p key={e} className="text-sm text-danger">{e}</p>)}
      <fieldset>
        <legend className="text-sm font-medium">Your usernames, if the CV leaves any out (optional)</legend>
        <p className="mb-2 text-xs text-muted">
          Leave a box empty if you have no account there. A username the CV itself states is the one checked.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {PLATFORMS.map(([name, label]) => (
            <Field key={name} label={label} name={name} defaultValue={value(name)} errors={state?.errors?.[name]} />
          ))}
        </div>
      </fieldset>
      <label className="block">
        <span className="mb-1 block text-sm font-medium">Anything the CV leaves out (optional)</span>
        <textarea name="note" rows={3} maxLength={2000} defaultValue={state?.values?.note}
          className="w-full rounded-md border border-line bg-background p-2 text-sm" />
        <span className="block text-xs text-muted">
          Shown beside the report to the people who read it, as your own words. Nothing in it is checked.
        </span>
        {state?.errors?.note?.map((e) => <span key={e} className="block text-sm text-danger">{e}</span>)}
      </label>
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
      <Button pending={pending}>Check this CV</Button>
    </form>
  );
}

/** Re-renders the page every few seconds while M5 is still working. */
export function Refresh({ seconds }: { seconds: number }) {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => router.refresh(), seconds * 1000);
    return () => clearInterval(timer);
  }, [router, seconds]);
  return null;
}

export function BeginTask({ sessionId, minutes }: { sessionId: string; minutes: number }) {
  const [state, action, pending] = useActionState(beginTask.bind(null, sessionId), undefined);
  return (
    <form action={action}>
      <Button pending={pending}>Start ({minutes} minutes)</Button>
      {state?.message && <p className="mt-1 text-sm text-danger">{state.message}</p>}
    </form>
  );
}

export function StartPractice({ patternId }: { patternId: string }) {
  const [state, action, pending] = useActionState(startPractice.bind(null, patternId), undefined);
  return (
    <form action={action}>
      <Button pending={pending}>Start</Button>
      {state?.message && <p className="mt-1 text-sm text-danger">{state.message}</p>}
    </form>
  );
}

export function Countdown({ deadline }: { deadline: string }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const timer = setInterval(tick, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, []);
  if (now === null) return null; // the server cannot know the browser's clock
  const left = Math.max(0, Math.floor((Date.parse(deadline) - now) / 1000));
  const text = left > 0 ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} left` : "The time is up";
  return <span className={left < 300 ? "text-danger" : "text-muted"}>{text}</span>;
}

/** The code editor: a textarea that keeps an unsent draft in this browser, so a refresh
 * does not lose work, and brings it back after either action (React resets a form once
 * its action has run). Tab indents instead of leaving the field. Run tries the visible
 * examples, as often as wanted, never scored; Submit runs the hidden tests, one attempt
 * of `maxAttempts`. */
export function Editor({ sessionId, starter, attempt, maxAttempts }: {
  sessionId: string; starter: string; attempt: number; maxAttempts: number; // `attempt`: the next one
}) {
  const [state, action, pending] = useActionState(submitSolution.bind(null, sessionId), undefined);
  const [run, runAction, running] = useActionState(runExamples.bind(null, sessionId), undefined);
  const area = useRef<HTMLTextAreaElement>(null);
  const key = `draft:${sessionId}`;

  useEffect(() => {
    try {
      const draft = localStorage.getItem(key);
      if (draft && area.current) area.current.value = draft;
    } catch {}
  }, [key, state, run]);

  function save() {
    try {
      if (area.current) localStorage.setItem(key, area.current.value);
    } catch {}
  }

  function tab(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Tab" || e.shiftKey) return;
    e.preventDefault();
    const el = e.currentTarget;
    el.setRangeText("    ", el.selectionStart, el.selectionEnd, "end");
    save();
  }

  const examples = run?.examples;
  return (
    <form action={action} className="space-y-3">
      <textarea
        ref={area} name="code" defaultValue={run?.values?.code ?? state?.values?.code ?? starter}
        onInput={save} onKeyDown={tab} spellCheck={false} autoCapitalize="off" autoComplete="off" rows={24}
        className="w-full rounded-md border border-line bg-background p-3 font-mono text-sm"
      />
      {[...(state?.errors?.code ?? []), ...(run?.errors?.code ?? [])].map((e) => <p key={e} className="text-sm text-danger">{e}</p>)}
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
      {run?.message && <p className="text-sm text-danger">{run.message}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" formAction={runAction} disabled={running || pending}
          className="rounded-md border border-accent px-4 py-2 font-medium text-accent disabled:opacity-60">
          {running ? "Running…" : "Run examples"}
        </button>
        <Button pending={pending}>Submit (attempt {attempt} of {maxAttempts})</Button>
      </div>
      <p className="text-xs text-muted">
        Run tries the visible examples as often as you like; it is not scored and uses no attempt. Submit runs the
        hidden tests. Your last attempt counts.
      </p>
      {examples && (
        <div className="rounded-md border border-line p-3 text-sm">
          <p className="font-medium">
            Examples: {examples.examples.filter((x) => x.passed).length} of {examples.examples.length} passed{" "}
            <span className="font-normal text-muted">(not scored)</span>
          </p>
          {examples.note && <p className="mt-1 font-mono text-xs">{examples.note}</p>}
          <ul className="mt-2 space-y-1">
            {examples.examples.map((x) => (
              <li key={x.name}>
                <span className={x.passed ? "text-ok" : "text-danger"}>{x.passed ? "✓" : "✗"}</span>{" "}
                <code>{x.name.replace(/^example_/, "").replaceAll("_", " ")}</code>
                {x.detail && <span className="block pl-5 font-mono text-xs text-muted">{x.detail}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </form>
  );
}

/** Count the last attempt now. It cannot be undone, so the browser asks first. */
export function FinishTask({ sessionId, attempt }: { sessionId: string; attempt: number }) {
  const [state, action, pending] = useActionState(finishTask.bind(null, sessionId), undefined);
  return (
    <form action={action} className="space-y-1">
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={pending}
          onClick={(e) => { if (!confirm(`Finish now? Attempt ${attempt} becomes your result.`)) e.preventDefault(); }}
          className="rounded-md border border-line px-4 py-2 font-medium disabled:opacity-60">
          {pending ? "Working…" : "Finish now"}
        </button>
        <span className="text-sm text-muted">Attempt {attempt} becomes your result, and no more can be made.</span>
      </div>
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
    </form>
  );
}
