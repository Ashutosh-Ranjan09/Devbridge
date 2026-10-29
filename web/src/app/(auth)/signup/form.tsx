"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { Button, Field } from "@/components/ui";

import { signup } from "../actions";

export function SignupForm() {
  const [state, action, pending] = useActionState(signup, undefined);
  const [role, setRole] = useState(state?.values?.role ?? "CANDIDATE");
  const v = state?.values;
  const e = state?.errors;
  return (
    <form action={action} className="space-y-4">
      <fieldset>
        <legend className="mb-1 text-sm font-medium">I am</legend>
        <div className="flex gap-4">
          {[["CANDIDATE", "a developer looking for work"], ["RECRUITER", "hiring"]].map(([value, label]) => (
            <label key={value} className="flex items-center gap-2">
              <input type="radio" name="role" value={value} checked={role === value}
                onChange={() => setRole(value)} />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      <Field label="Name" name="name" autoComplete="name" defaultValue={v?.name} errors={e?.name} />
      <Field label="Email" name="email" type="email" autoComplete="email" defaultValue={v?.email} errors={e?.email} />
      <Field label="Password (at least 10 characters)" name="password" type="password"
        autoComplete="new-password" errors={e?.password} />
      {role === "RECRUITER" && (
        <>
          <Field label="Organisation" name="orgName" autoComplete="organization"
            defaultValue={v?.orgName} errors={e?.orgName} />
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Hiring as</span>
            <select name="orgKind" defaultValue={v?.orgKind ?? "ENTERPRISE"}
              className="w-full rounded-md border border-line bg-background px-3 py-2">
              <option value="ENTERPRISE">a company (enterprise recruiting)</option>
              <option value="CLIENT">a freelance client</option>
            </select>
          </label>
        </>
      )}
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
      <div className="flex items-center gap-4">
        <Button pending={pending}>Create account</Button>
        <Link href="/login" className="text-sm text-accent underline">I have an account</Link>
      </div>
    </form>
  );
}
