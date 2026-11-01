"use client";

import { useActionState } from "react";

import { AuthField, AuthHeading, AuthMessage, AuthSubmit, AuthSwitch } from "@/components/auth";

import { login } from "../actions";

export function LoginForm({ onSwitch }: { onSwitch: () => void }) {
  const [state, action, pending] = useActionState(login, undefined);
  return (
    <form action={action} className="mx-auto max-w-sm">
      <AuthHeading title="Log in" subtitle="Developers, recruiters and admins all log in here." />
      <div className="space-y-4">
        <AuthField label="Email" name="email" type="email" icon="Mail" autoComplete="email"
          defaultValue={state?.values?.email} errors={state?.errors?.email} />
        <AuthField label="Password" name="password" type="password" icon="Lock" autoComplete="current-password"
          errors={state?.errors?.password} />
        {state?.message && <AuthMessage>{state.message}</AuthMessage>}
        <AuthSubmit pending={pending}>Log in</AuthSubmit>
      </div>
      <p className="mt-5 text-center text-xs leading-relaxed text-muted">
        Forgot your password? An admin can give you a one-time reset link.
      </p>
      <AuthSwitch prompt="New to DevBridge?" action="Create an account" onClick={onSwitch} />
    </form>
  );
}
