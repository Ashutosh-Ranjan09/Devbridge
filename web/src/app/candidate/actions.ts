"use server";

import { redirect } from "next/navigation";
import * as z from "zod";

import { requireCandidate, myAssessment } from "@/lib/candidate";
import { db } from "@/lib/db";
import { CvSchema, type FormState, SubmissionSchema } from "@/lib/definitions";
import { call, ServiceError } from "@/lib/services";
import { forwardAssessment } from "@/lib/sync";
import type { CandidateResult, Task } from "@/lib/types";

/** Every action starts with requireCandidate(): an action is a POST endpoint anyone can
 * call, whether or not they came from the page. */

export async function uploadCv(_: FormState, form: FormData): Promise<FormState> {
  const me = await requireCandidate();
  const parsed = CvSchema.safeParse({ cv: form.get("cv") });
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors };
  const { cv } = parsed.data;

  const upload = new FormData();
  upload.set("document", cv, cv.name);
  // The subject_ref, never a name: the report and everything M6 derives from it is
  // filed under this reference.
  upload.set("subject", JSON.stringify({ subject_ref: me.subjectRef }));
  upload.set("options", JSON.stringify({ narrative: true }));
  let id: string;
  try {
    ({ verification_id: id } = await call<{ verification_id: string }>("m5", "/v1/verifications", { form: upload }));
  } catch (e) {
    if (e instanceof ServiceError) return { message: e.message };
    throw e;
  }
  await db.verification.create({ data: { id, candidateId: me.id, fileName: cv.name } });
  redirect(`/candidate/cv/${id}`);
}

export async function startPractice(patternId: string): Promise<FormState> {
  const me = await requireCandidate();
  let id: string;
  try {
    // Asking again returns the task already issued (assessment's rule), so a second
    // click, or a refresh, opens the same task rather than fishing for an easier one.
    const { tasks } = await call<{ tasks: Task[] }>("assess", "/v1/sessions", {
      body: { candidate_ref: me.subjectRef, pattern_id: patternId },
    });
    id = tasks[0].session_id;
  } catch (e) {
    if (e instanceof ServiceError) return { message: e.message };
    throw e;
  }
  await db.assessment.upsert({ where: { id }, create: { id, candidateId: me.id }, update: {} });
  redirect(`/candidate/assessments/${id}`);
}

export async function submitSolution(id: string, _: FormState, form: FormData): Promise<FormState> {
  const me = await requireCandidate();
  await myAssessment(me.id, id);
  const parsed = SubmissionSchema.safeParse({ code: form.get("code") });
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors };
  try {
    await call<CandidateResult>("assess", `/v1/sessions/${encodeURIComponent(id)}/submit`, {
      body: { code: parsed.data.code },
      timeoutMs: 90_000, // the sandbox's 30 s, plus starting a container
    });
  } catch (e) {
    // 503: the sandbox could not run, nothing was measured, the session is still open.
    // 409: already submitted, or past the deadline. The module's message says which.
    if (e instanceof ServiceError) return { message: e.message };
    throw e;
  }
  // The result is stored by the assessment module either way; if M6 is down, the
  // skills page tries again later.
  await forwardAssessment(id).catch(() => {});
  redirect(`/candidate/assessments/${id}`);
}
