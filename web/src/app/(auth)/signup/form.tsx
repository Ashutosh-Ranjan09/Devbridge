"use client";

import { useActionState, useState } from "react";

import { AuthField, AuthHeading, AuthMessage, AuthSubmit, AuthSwitch } from "@/components/auth";
import { Icon } from "@/components/icons";

import { signup } from "../actions";

const ROLES = [
  { value: "CANDIDATE", title: "Developer", hint: "Verify my CV", icon: "Code" },
  { value: "RECRUITER", title: "Recruiter", hint: "Hire with evidence", icon: "Briefcase" },
] as const;

export function SignupForm({ onSwitch }: { onSwitch: () => void }) {
  const [state, action, pending] = useActionState(signup, undefined);
  const [role, setRole] = useState(state?.values?.role ?? "CANDIDATE");
  const v = state?.values;
  const e = state?.errors;
  return (
    <form action={action} className="mx-auto max-w-sm">
      <AuthHeading title="Create an account" subtitle="Skills backed by evidence, not keywords." />
      {/* Buttons and a hidden input, not radios: React resets a form after its action
          runs, which would put a refused recruiter's radios back on Developer while the
          recruiter fields stay open. */}
      <input type="hidden" name="role" value={role} />
      <div role="radiogroup" aria-label="I am" className="mb-5 grid grid-cols-2 gap-3 short:mb-4">
        {ROLES.map((r) => {
          const Glyph = Icon[r.icon];
          const on = role === r.value;
          return (
            <button
              key={r.value} type="button" role="radio" aria-checked={on} onClick={() => setRole(r.value)}
              className={`flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left short:py-2 transition focus-visible:ring-4 focus-visible:ring-brand/20 focus-visible:outline-none ${on ? "border-brand bg-brand-soft" : "border-line hover:border-brand/60"}`}
            >
              <span className={`grid size-9 shrink-0 place-items-center rounded-lg ${on ? "bg-brand text-white" : "bg-background text-muted"}`}>
                <Glyph className="size-[18px]" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{r.title}</span>
                <span className="block truncate text-xs text-muted">{r.hint}</span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="space-y-3.5 short:space-y-3">
        <AuthField label="Full name" name="name" icon="User" autoComplete="name" defaultValue={v?.name} errors={e?.name} />
        <AuthField label="Email" name="email" type="email" icon="Mail" autoComplete="email" defaultValue={v?.email} errors={e?.email} />
        <AuthField label="Password (at least 10 characters)" name="password" type="password" icon="Lock"
          autoComplete="new-password" errors={e?.password} />
        {role === "RECRUITER" && (
          <>
            <AuthField label="Organisation" name="orgName" icon="Building" autoComplete="organization"
              defaultValue={v?.orgName} errors={e?.orgName} />
            <label className="block">
              <span className="sr-only">Hiring as</span>
              <span className="relative block">
                <Icon.Briefcase className="pointer-events-none absolute top-1/2 left-4 size-[18px] -translate-y-1/2 text-muted" />
                <select name="orgKind" key={v?.orgKind} defaultValue={v?.orgKind ?? "ENTERPRISE"}
                  className="h-12 w-full appearance-none short:h-11 rounded-xl border border-line bg-background pr-10 pl-11 text-[15px] outline-none transition focus:border-brand focus:ring-4 focus:ring-brand/15">
                  <option value="ENTERPRISE">Hiring for a company</option>
                  <option value="CLIENT">Hiring as a freelance client</option>
                </select>
                <Icon.Chevron className="pointer-events-none absolute top-1/2 right-4 size-4 -translate-y-1/2 text-muted" />
              </span>
              {e?.orgKind?.map((m) => <span key={m} className="mt-1.5 block pl-1 text-sm text-danger">{m}</span>)}
            </label>
          </>
        )}
        {state?.message && <AuthMessage>{state.message}</AuthMessage>}
        <div className="pt-1.5">
          <AuthSubmit pending={pending}>Create account</AuthSubmit>
        </div>
      </div>
      <AuthSwitch prompt="Already have an account?" action="Log in" onClick={onSwitch} />
    </form>
  );
}
