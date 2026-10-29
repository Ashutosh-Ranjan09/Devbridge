"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useRef, useState } from "react";

import { startPractice, submitSolution, uploadCv } from "@/app/candidate/actions";

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
 * does not lose work. Tab indents instead of leaving the field. */
export function Editor({ sessionId, starter }: { sessionId: string; starter: string }) {
  const [state, action, pending] = useActionState(submitSolution.bind(null, sessionId), undefined);
  const area = useRef<HTMLTextAreaElement>(null);
  const key = `draft:${sessionId}`;

  useEffect(() => {
    try {
      const draft = localStorage.getItem(key);
      if (draft && area.current) area.current.value = draft;
    } catch {}
  }, [key]);

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

  return (
    <form action={action} className="space-y-3">
      <textarea
        ref={area} name="code" defaultValue={state?.values?.code ?? starter} onInput={save} onKeyDown={tab}
        spellCheck={false} autoCapitalize="off" autoComplete="off" rows={24}
        className="w-full rounded-md border border-line bg-background p-3 font-mono text-sm"
      />
      {state?.errors?.code?.map((e) => <p key={e} className="text-sm text-danger">{e}</p>)}
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
      <div className="flex items-center gap-3">
        <Button pending={pending}>Submit</Button>
        <span className="text-sm text-muted">One submission. It runs against hidden tests in a sandbox.</span>
      </div>
    </form>
  );
}
