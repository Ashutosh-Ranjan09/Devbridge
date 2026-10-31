"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";

import { beginTask, startPractice } from "@/app/candidate/actions";

import { Button } from "./ui";

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
  return <span className={left < 300 ? "text-danger" : ""}>{text}</span>;
}
