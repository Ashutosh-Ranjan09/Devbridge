"use server";

import { randomBytes } from "node:crypto";

import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import * as z from "zod";

import { requireRole } from "@/lib/auth";
import { db } from "@/lib/db";
import { type FormState, MarkSchema, typed } from "@/lib/definitions";
import { lineKeys } from "@/lib/review";
import { call, ServiceError } from "@/lib/services";
import { hashToken } from "@/lib/session";
import type { Report } from "@/lib/types";

/** One line of one of this candidate's reports, marked by an admin. The key is checked
 * against the report itself, so a hand-made POST cannot mark a line that does not exist. */
export async function markLine(userId: string, verificationId: string, key: string,
                               _: FormState, form: FormData): Promise<FormState> {
  const me = await requireRole("ADMIN");
  const v = await db.verification.findFirst({ where: { id: verificationId, candidateId: userId } });
  if (!v) return { message: "No such report for this candidate." };
  const parsed = MarkSchema.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: typed(form) };
  let report: Report;
  try {
    report = await call<Report>("m5", `/v1/verifications/${encodeURIComponent(v.id)}`);
  } catch (e) {
    if (e instanceof ServiceError) return { message: e.message, values: typed(form) };
    throw e;
  }
  if (!lineKeys(report).has(key)) return { message: "That line is not in this report." };
  await db.itemReview.create({ data: { verificationId: v.id, itemKey: key, reviewedById: me.id, ...parsed.data } });
  revalidatePath(`/admin/candidates/${userId}`);
  return { message: "Marked." };
}

const RESET_LIFETIME_MS = 24 * 60 * 60 * 1000;

/** A one-time link to set a new password, for the admin to hand over. Shown once:
 * only its hash is stored. A new link cancels any unused one for the same person. */
export async function makeResetLink(userId: string): Promise<FormState & { link?: string }> {
  const me = await requireRole("ADMIN");
  if (userId === me.id) return { message: "Not for your own account." };
  const user = await db.user.findUnique({ where: { id: userId } });
  if (!user) return { message: "No such account." };
  const token = randomBytes(32).toString("base64url");
  await db.$transaction([
    db.passwordReset.deleteMany({ where: { userId, usedAt: null } }),
    db.passwordReset.create({
      data: { tokenHash: hashToken(token), userId, createdById: me.id, expiresAt: new Date(Date.now() + RESET_LIFETIME_MS) },
    }),
  ]);
  const h = await headers();
  return { link: `${h.get("x-forwarded-proto") ?? "http"}://${h.get("host")}/reset/${token}` };
}
