"use client";

import { useActionState } from "react";

import { markLine } from "@/app/admin/actions";

export function MarkForm({ userId, verificationId, lineKey }: { userId: string; verificationId: string; lineKey: string }) {
  const [state, action, pending] = useActionState(markLine.bind(null, userId, verificationId, lineKey), undefined);
  return (
    <form action={action} className="mt-2 flex flex-wrap items-start gap-2 text-sm">
      {[["VERIFIED", "Verified"], ["UNVERIFIED", "Unverified"]].map(([value, label]) => (
        <label key={value} className="flex items-center gap-1">
          <input type="radio" name="mark" value={value} defaultChecked={state?.values?.mark === value} />{label}
        </label>
      ))}
      <input name="note" placeholder="What you checked" defaultValue={state?.values?.note}
        className="min-w-48 flex-1 rounded-md border border-line bg-background px-2 py-1" />
      <button type="submit" disabled={pending} className="rounded-md border border-line px-3 py-1 disabled:opacity-60">
        {pending ? "…" : "Mark"}
      </button>
      {[...(state?.errors?.mark ?? []), ...(state?.errors?.note ?? [])].map((e) => (
        <p key={e} className="w-full text-danger">{e}</p>
      ))}
      {state?.message && <p className="w-full">{state.message}</p>}
    </form>
  );
}
