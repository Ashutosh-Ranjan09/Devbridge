"use client";

import Link from "next/link";
import { useActionState } from "react";

import { Button, Field } from "@/components/ui";

import { login } from "../actions";

export function LoginForm() {
  const [state, action, pending] = useActionState(login, undefined);
  return (
    <form action={action} className="space-y-4">
      <Field label="Email" name="email" type="email" autoComplete="email"
        defaultValue={state?.values?.email} errors={state?.errors?.email} />
      <Field label="Password" name="password" type="password" autoComplete="current-password"
        errors={state?.errors?.password} />
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
      <div className="flex items-center gap-4">
        <Button pending={pending}>Log in</Button>
        <Link href="/signup" className="text-sm text-accent underline">Create an account</Link>
      </div>
    </form>
  );
}
