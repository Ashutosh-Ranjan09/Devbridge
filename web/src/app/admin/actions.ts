"use server";

import { revalidatePath } from "next/cache";
import * as z from "zod";

import { requireRole } from "@/lib/auth";
import { db } from "@/lib/db";
import { type FormState, MarkSchema, typed } from "@/lib/definitions";
import { lineKeys } from "@/lib/review";
import { call, ServiceError } from "@/lib/services";
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
