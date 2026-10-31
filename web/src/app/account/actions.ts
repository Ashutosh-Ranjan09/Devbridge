"use server";

import * as z from "zod";

import { requireUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { ChangePasswordSchema, type FormState } from "@/lib/definitions";
import { clearFailures, lockedFor, recordFailure } from "@/lib/limits";
import { hashPassword, verifyPassword } from "@/lib/password";
import { endOtherSessions } from "@/lib/session";

/** A new password, given the current one. A wrong current password counts against the
 * same limit as a wrong login, so a session left open on someone else's screen cannot
 * be used to guess it. Every other session ends; this one stays signed in. */
export async function changePassword(_: FormState, form: FormData): Promise<FormState> {
  const me = await requireUser();
  const parsed = ChangePasswordSchema.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors };
  const wait = await lockedFor(me.email);
  if (wait) return { message: `Too many wrong attempts. Try again in ${wait} minute${wait === 1 ? "" : "s"}.` };
  const { passwordHash } = await db.user.findUniqueOrThrow({ where: { id: me.id }, select: { passwordHash: true } });
  if (!(await verifyPassword(parsed.data.current, passwordHash))) {
    await recordFailure(me.email);
    return { errors: { current: ["That is not your current password."] } };
  }
  await db.user.update({ where: { id: me.id }, data: { passwordHash: await hashPassword(parsed.data.password) } });
  await clearFailures(me.email);
  await endOtherSessions(me.id);
  return { message: "Password changed. Other devices have been logged out." };
}
