"use client";

import { useActionState } from "react";

import { Button, Field } from "@/components/ui";

import { changePassword } from "./actions";

export function ChangePasswordForm() {
  const [state, action, pending] = useActionState(changePassword, undefined);
  return (
    <form action={action} className="space-y-4">
      <Field label="Current password" name="current" type="password" autoComplete="current-password"
        errors={state?.errors?.current} />
      <Field label="New password" name="password" type="password" autoComplete="new-password"
        errors={state?.errors?.password} />
      <p className="text-sm text-muted">At least 10 characters. Other devices are logged out.</p>
      {state?.message && <p className="text-sm">{state.message}</p>}
      <Button pending={pending}>Change password</Button>
    </form>
  );
}
