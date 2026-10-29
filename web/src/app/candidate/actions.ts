"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import * as z from "zod";

import { requireCandidate, myAssessment } from "@/lib/candidate";
import { db } from "@/lib/db";
import { CvSchema, type FormState, HANDLE_FIELDS, HandlesSchema, SubmissionSchema, typed } from "@/lib/definitions";
import { call, ServiceError } from "@/lib/services";
import { forwardAssessment } from "@/lib/sync";
import type { CandidateResult, Task } from "@/lib/types";

/** Every action starts with requireCandidate(): an action is a POST endpoint anyone can
 * call, whether or not they came from the page. */

export async function uploadCv(_: FormState, form: FormData): Promise<FormState> {
  const me = await requireCandidate();
  const parsed = CvSchema.safeParse({ cv: form.get("cv") });
  const typedHandles = HandlesSchema.safeParse(Object.fromEntries(HANDLE_FIELDS.map((k) => [k, form.get(k) ?? ""])));
  if (!parsed.success || !typedHandles.success) {
    return {
      errors: {
        ...(parsed.success ? {} : z.flattenError(parsed.error).fieldErrors),
        ...(typedHandles.success ? {} : z.flattenError(typedHandles.error).fieldErrors),
      },
      values: typed(form),
    };
  }
  const { cv } = parsed.data;
  const handles = Object.fromEntries(Object.entries(typedHandles.data).filter(([, v]) => v !== null));

  const upload = new FormData();
  upload.set("document", cv, cv.name);
  // The subject_ref, never a name: the report and everything M6 derives from it is
  // filed under this reference.
  upload.set("subject", JSON.stringify({ subject_ref: me.subjectRef }));
  upload.set("options", JSON.stringify({ narrative: true }));
  // Usernames the candidate typed; M5 uses each only where the CV names none.
  if (Object.keys(handles).length) upload.set("handles", JSON.stringify(handles));
  let id: string;
  try {
    ({ verification_id: id } = await call<{ verification_id: string }>("m5", "/v1/verifications", { form: upload }));
  } catch (e) {
    if (e instanceof ServiceError) return { message: e.message, values: typed(form) };
    throw e;
  }
  const h = typedHandles.data;
  await db.$transaction([
    db.verification.create({ data: { id, candidateId: me.id, fileName: cv.name } }),
    db.candidate.update({
      where: { userId: me.id },
      data: { githubHandle: h.github, codeforcesHandle: h.codeforces, leetcodeHandle: h.leetcode, codechefHandle: h.codechef },
    }),
  ]);
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
  // The code goes back with every refusal: React resets the form after the action, and
  // a candidate whose submission the sandbox could not run must not lose their work.
  const code = String(form.get("code") ?? "");
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: { code } };
  try {
    await call<CandidateResult>("assess", `/v1/sessions/${encodeURIComponent(id)}/submit`, {
      body: { code: parsed.data.code },
      timeoutMs: 90_000, // the sandbox's 30 s, plus starting a container
    });
  } catch (e) {
    // 503: the sandbox could not run, nothing was measured, the session is still open.
    // 409: already submitted, or past the deadline. The module's message says which.
    if (e instanceof ServiceError) return { message: e.message, values: { code } };
    throw e;
  }
  // A job's task, once submitted, is the recruiter's to read.
  const row = await db.assessment.findUniqueOrThrow({ where: { id } });
  if (row.applicationId) {
    await db.application.updateMany({
      where: { id: row.applicationId, status: "ASSESSMENT_SENT" },
      data: { status: "SUBMITTED" },
    });
  }
  // The result is stored by the assessment module either way; if M6 is down, the
  // skills page tries again later.
  await forwardAssessment(id).catch(() => {});
  redirect(`/candidate/assessments/${id}`);
}

export async function applyToJob(jobId: string): Promise<FormState> {
  const me = await requireCandidate();
  // Only an open job, which only a confirmed job can be.
  const job = await db.job.findFirst({ where: { id: jobId, open: true } });
  if (!job) return { message: "This job is not open." };
  await db.application.upsert({
    where: { jobId_candidateId: { jobId, candidateId: me.id } },
    create: { jobId, candidateId: me.id },
    update: {},
  });
  revalidatePath("/candidate/jobs");
  return undefined;
}
