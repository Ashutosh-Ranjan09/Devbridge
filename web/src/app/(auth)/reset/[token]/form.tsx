"use client";

import { useActionState } from "react";

import { Button, Field } from "@/components/ui";

import { resetPassword } from "../../actions";

export function ResetForm({ token }: { token: string }) {
  const [state, action, pending] = useActionState(resetPassword.bind(null, token), undefined);
  return (
    <form action={action} className="space-y-4">
      <Field label="New password" name="password" type="password" autoComplete="new-password"
        errors={state?.errors?.password} />
      <p className="text-sm text-muted">At least 10 characters. This logs you out everywhere else.</p>
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
      <Button pending={pending}>Set password and log in</Button>
    </form>
  );
}
