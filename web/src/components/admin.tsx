"use client";

import { useActionState } from "react";

import { makeResetLink, markLine } from "@/app/admin/actions";

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

/** Makes a one-time reset link for the chosen account and shows it once; leaving the
 * page loses it, and a new one cancels it. */
export function ResetLink({ accounts }: { accounts: { id: string; label: string }[] }) {
  const [state, action, pending] = useActionState(
    (_: unknown, form: FormData) => makeResetLink(String(form.get("userId") ?? "")),
    undefined,
  );
  return (
    <form action={action} className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <select name="userId" className="min-w-0 flex-1 rounded-md border border-line bg-background px-2 py-1 text-sm">
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
        <button type="submit" disabled={pending}
          className="rounded-md border border-line px-3 py-1 text-sm disabled:opacity-60">
          {pending ? "…" : "Make a reset link"}
        </button>
      </div>
      {state?.link && (
        <>
          <input readOnly value={state.link} onFocus={(e) => e.currentTarget.select()}
            className="w-full rounded-md border border-line bg-background px-2 py-1 font-mono text-xs" />
          <p className="text-xs text-muted">Give this to that person only. It works once, for 24 hours.</p>
        </>
      )}
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
    </form>
  );
}
