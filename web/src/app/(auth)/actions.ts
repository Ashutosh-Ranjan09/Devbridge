"use server";

import { randomBytes } from "node:crypto";

import { redirect } from "next/navigation";
import * as z from "zod";

import { Prisma } from "@/generated/prisma/client";
import { HOME } from "@/lib/auth";
import { db } from "@/lib/db";
import { type FormState, LoginSchema, SignupSchema } from "@/lib/definitions";
import { clearFailures, lockedFor, recordFailure } from "@/lib/limits";
import { hashPassword, verifyPassword } from "@/lib/password";
import { createSession, deleteSession } from "@/lib/session";

const TAKEN = { email: ["An account with this email exists. Log in instead."] };

/** The values to put back in the form after an error. Never the password. */
function kept(form: FormData): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of form) if (k !== "password" && typeof v === "string") out[k] = v;
  return out;
}

/** A subject_ref the modules will know this candidate by. Random, so it says nothing
 * about the person and links them to nothing they did not do here. */
function newSubjectRef(): string {
  return `subject:${randomBytes(8).toString("hex")}`;
}

export async function signup(_: FormState, form: FormData): Promise<FormState> {
  const parsed = SignupSchema.safeParse(Object.fromEntries(form));
  if (!parsed.success) {
    return { errors: z.flattenError(parsed.error).fieldErrors, values: kept(form) };
  }
  const d = parsed.data;
  let userId: string;
  let role: keyof typeof HOME;
  try {
    const user = await db.user.create({
      data: {
        email: d.email,
        name: d.name,
        passwordHash: await hashPassword(d.password),
        role: d.role,
        ...(d.role === "CANDIDATE"
          ? { candidate: { create: { subjectRef: newSubjectRef() } } }
          : { memberships: { create: { org: { create: { name: d.orgName, kind: d.orgKind } } } } }),
      },
    });
    userId = user.id;
    role = user.role;
  } catch (e) {
    // The unique index on email, not a lookup first: two sign-ups at once cannot both pass.
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === "P2002") {
      return { errors: TAKEN, values: kept(form) };
    }
    throw e;
  }
  await createSession(userId);
  redirect(HOME[role]);
}

export async function login(_: FormState, form: FormData): Promise<FormState> {
  const parsed = LoginSchema.safeParse(Object.fromEntries(form));
  if (!parsed.success) {
    return { errors: z.flattenError(parsed.error).fieldErrors, values: kept(form) };
  }
  const { email, password } = parsed.data;
  // Before the password is compared: a locked email gets the same answer whether or not
  // it has an account, and whether or not the password is right.
  const wait = await lockedFor(email);
  if (wait) {
    return {
      message: `Too many wrong attempts for this email. Try again in ${wait} minute${wait === 1 ? "" : "s"}.`,
      values: kept(form),
    };
  }
  const user = await db.user.findUnique({ where: { email } });
  // Always a bcrypt comparison, and one message for both failures: neither the timing
  // nor the wording says whether the email has an account.
  const ok = await verifyPassword(password, user?.passwordHash);
  if (!user || !ok) {
    await recordFailure(email);
    return { message: "Email or password is wrong.", values: kept(form) };
  }
  await clearFailures(email);
  await createSession(user.id);
  redirect(HOME[user.role]);
}

export async function logout(): Promise<void> {
  await deleteSession();
  redirect("/login");
}
