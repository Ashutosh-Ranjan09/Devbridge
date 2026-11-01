"use client";

import { useActionState } from "react";

import type { FormState } from "@/lib/definitions";

import { Button } from "./ui";

/** A one-button form for a bound server action, with its pending state and message. */
export function ActionButton({ action, label, note, variant }: {
  action: (state: FormState, form: FormData) => Promise<FormState>;
  label: string;
  note?: string;
  variant?: "solid" | "outline";
}) {
  const [state, run, pending] = useActionState(action, undefined);
  return (
    <form action={run} className="inline-block">
      <Button pending={pending} variant={variant}>{label}</Button>
      {note && <span className="ml-3 text-sm text-muted">{note}</span>}
      {state?.message && <p className="mt-1 text-sm">{state.message}</p>}
    </form>
  );
}
