"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import * as z from "zod";

import { requireCandidate, myAssessment } from "@/lib/candidate";
import { db } from "@/lib/db";
import {
  CvSchema, type FormState, HANDLE_FIELDS, HandlesSchema, MAX_CVS_PER_DAY, NoteSchema, ProofSchema, type RunState,
  SubmissionSchema, typed,
} from "@/lib/definitions";
import { removeFile, saveFile } from "@/lib/files";
import { call, ServiceError } from "@/lib/services";
import { settleAssessment } from "@/lib/sync";
import type { CandidateResult, Examples, Report, Running, Submitted, Task } from "@/lib/types";

/** Every action starts with requireCandidate(): an action is a POST endpoint anyone can
 * call, whether or not they came from the page. */

export async function uploadCv(_: FormState, form: FormData): Promise<FormState> {
  const me = await requireCandidate();
  const parsed = CvSchema.safeParse({ cv: form.get("cv") });
  const typedHandles = HandlesSchema.safeParse(Object.fromEntries(HANDLE_FIELDS.map((k) => [k, form.get(k) ?? ""])));
  const note = NoteSchema.safeParse(form.get("note") ?? "");
  if (!parsed.success || !typedHandles.success || !note.success) {
    return {
      errors: {
        ...(parsed.success ? {} : z.flattenError(parsed.error).fieldErrors),
        ...(typedHandles.success ? {} : z.flattenError(typedHandles.error).fieldErrors),
        ...(note.success ? {} : { note: note.error.issues.map((i) => i.message) }),
      },
      values: typed(form),
    };
  }
  const { cv } = parsed.data;
  const handles = Object.fromEntries(Object.entries(typedHandles.data).filter(([, v]) => v !== null));

  // One CV per developer: a check still running finishes first, and a few a day at most.
  const previous = await db.verification.findMany({
    where: { candidateId: me.id }, orderBy: { createdAt: "desc" }, include: { proofs: true },
  });
  const lastDay = previous.filter((v) => v.createdAt.getTime() > Date.now() - 24 * 60 * 60 * 1000).length;
  if (lastDay >= MAX_CVS_PER_DAY) {
    return { message: `At most ${MAX_CVS_PER_DAY} CVs a day: try again tomorrow.`, values: typed(form) };
  }
  if (previous[0]) {
    const last = await call<Report | Running>("m5", `/v1/verifications/${encodeURIComponent(previous[0].id)}`).catch(() => null);
    if (last?.status === "running") {
      return { message: "Your last CV is still being checked: wait for it to finish.", values: typed(form) };
    }
  }

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
    // The note stays here: it is the candidate's own words, never sent to a module.
    db.verification.create({ data: { id, candidateId: me.id, fileName: cv.name, note: note.data } }),
    db.candidate.update({
      where: { userId: me.id },
      data: { githubHandle: h.github, codeforcesHandle: h.codeforces, leetcodeHandle: h.leetcode, codechefHandle: h.codechef },
    }),
  ]);
  // Kept so the candidate (and the recruiters they apply to) can see the CV itself.
  await saveFile("cv", id, cv.name, cv);
  // The old CV counts nowhere now: M6 keeps only the newest check, the pages show only
  // the newest. Its file and its proofs go; its row stays, a link to M5's report.
  for (const old of previous) {
    await removeFile("cv", old.id, old.fileName);
    for (const p of old.proofs) await removeFile("proofs", p.id, p.fileName);
  }
  await db.proof.deleteMany({ where: { verificationId: { in: previous.map((v) => v.id) } } });
  revalidatePath("/candidate/cv");
  redirect("/candidate/cv");
}

/** A document backing one line of the CV (`claimId`, M5's) or the candidate's own. Kept
 * here only: never sent to a module, and the system checks nothing in it. */
export async function addProof(claimId: string | null, _: FormState, form: FormData): Promise<FormState> {
  const me = await requireCandidate();
  const cv = await db.verification.findFirst({ where: { candidateId: me.id }, orderBy: { createdAt: "desc" } });
  if (!cv) return { message: "Upload your CV first." };
  const parsed = ProofSchema.safeParse({ file: form.get("file"), label: form.get("label") });
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: typed(form) };
  const { file, label } = parsed.data;
  const proof = await db.proof.create({ data: { verificationId: cv.id, claimId, label, fileName: file.name } });
  try {
    await saveFile("proofs", proof.id, file.name, file);
  } catch (e) {
    await db.proof.delete({ where: { id: proof.id } });
    throw e;
  }
  revalidatePath("/candidate/cv");
  return undefined;
}

export async function removeProof(id: string): Promise<FormState> {
  const me = await requireCandidate();
  // Through its owner: another candidate's proof id is the same "not found".
  const proof = await db.proof.findFirst({ where: { id, verification: { candidateId: me.id } } });
  if (!proof) return { message: "That document is not yours or no longer exists." };
  await db.proof.delete({ where: { id } });
  await removeFile("proofs", id, proof.fileName);
  revalidatePath("/candidate/cv");
  return undefined;
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

/** Start a job's task: the clock runs from now and the task is shown. Pressing again on
 * a task already begun changes nothing (assessment's rule). */
export async function beginTask(id: string): Promise<FormState> {
  const me = await requireCandidate();
  await myAssessment(me.id, id);
  try {
    await call<Task>("assess", `/v1/sessions/${encodeURIComponent(id)}/begin`, { method: "POST" });
  } catch (e) {
    // 409: the start-by date passed. The module's message says when.
    if (e instanceof ServiceError) return { message: e.message };
    throw e;
  }
  redirect(`/candidate/assessments/${id}`);
}

/** The Run button: the visible examples, as often as the candidate likes. Nothing is
 * stored and no attempt is used, so the answer comes back to the form, not the page. */
export async function runExamples(id: string, _: RunState, form: FormData): Promise<RunState> {
  const me = await requireCandidate();
  await myAssessment(me.id, id);
  const parsed = SubmissionSchema.safeParse({ code: form.get("code") });
  const code = String(form.get("code") ?? "");
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: { code } };
  try {
    const examples = await call<Examples>("assess", `/v1/sessions/${encodeURIComponent(id)}/run`, {
      body: { code: parsed.data.code },
      timeoutMs: 90_000, // the sandbox's 30 s, plus starting a container
    });
    return { examples, values: { code } };
  } catch (e) {
    // 422: the code does not parse (the line is in the message). 503: the sandbox is down.
    if (e instanceof ServiceError) return { message: e.message, values: { code } };
    throw e;
  }
}

export async function submitSolution(id: string, _: FormState, form: FormData): Promise<FormState> {
  const me = await requireCandidate();
  await myAssessment(me.id, id);
  const parsed = SubmissionSchema.safeParse({ code: form.get("code") });
  // The code goes back with every refusal: React resets the form after the action, and
  // a candidate whose submission the sandbox could not run must not lose their work.
  const code = String(form.get("code") ?? "");
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: { code } };
  let answer: Submitted;
  try {
    answer = await call<Submitted>("assess", `/v1/sessions/${encodeURIComponent(id)}/submit`, {
      body: { code: parsed.data.code },
      timeoutMs: 90_000, // the sandbox's 30 s, plus starting a container
    });
  } catch (e) {
    // 422: does not parse, no attempt used. 503: the sandbox could not run, nothing used.
    // 409: final already, or past the deadline. The module's message says which.
    if (e instanceof ServiceError) return { message: e.message, values: { code } };
    throw e;
  }
  if (answer.final) await settleAssessment(id);
  redirect(`/candidate/assessments/${id}`);
}

/** Done before the attempts run out: the last attempt counts now. */
export async function finishTask(id: string): Promise<FormState> {
  const me = await requireCandidate();
  await myAssessment(me.id, id);
  try {
    await call<CandidateResult>("assess", `/v1/sessions/${encodeURIComponent(id)}/finish`, { method: "POST" });
  } catch (e) {
    if (e instanceof ServiceError) return { message: e.message };
    throw e;
  }
  await settleAssessment(id);
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
  revalidatePath("/candidate");
  return undefined;
}
