"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import * as z from "zod";

import { db } from "@/lib/db";
import { BarSchema, DecisionSchema, type FormState, NewJobSchema, StartBySchema, typed } from "@/lib/definitions";
import { myApplication, myJob, requireRecruiter } from "@/lib/recruiter";
import { call, ServiceError } from "@/lib/services";
import { endOfDay } from "@/lib/tasks";
import type { Job, Task } from "@/lib/types";

/** Every action re-checks the recruiter and that the job is one of their organisation's:
 * an action is a POST anyone can send, whether or not they came from the page. */

const jobPath = (id: string) => `/recruiter/jobs/${encodeURIComponent(id)}`;

/** A module's refusal, with what was typed so the form shows it again: React resets a
 * form after its action runs, and a field with no value passed back comes back empty. */
function refused(e: unknown, form?: FormData): FormState {
  if (e instanceof ServiceError) return { message: e.message, values: form ? typed(form) : undefined };
  throw e;
}

export async function createJob(_: FormState, form: FormData): Promise<FormState> {
  const me = await requireRecruiter();
  const parsed = NewJobSchema.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: typed(form) };
  const d = parsed.data;
  if (!me.orgIds.includes(d.orgId)) return { errors: { orgId: ["Not one of your organisations."] }, values: typed(form) };
  let job: Job;
  try {
    // The model proposes skills, each quoted from the JD; with it, this can take minutes.
    job = await call<Job>("assess", "/v1/jobs", { body: { text: d.text, model: d.model === "on" }, timeoutMs: 240_000 });
  } catch (e) {
    return refused(e, form);
  }
  await db.job.create({ data: { id: job.job_id, title: d.title, orgId: d.orgId, createdById: me.id } });
  redirect(jobPath(job.job_id));
}

/** The skills table as a person left it. Each row's `priority:<id>` is must, nice or drop;
 * `bar:<id>` is blank or 0–1. A new skill comes in as `add` with `addPriority`. */
export async function editJob(id: string, _: FormState, form: FormData): Promise<FormState> {
  const me = await requireRecruiter();
  await myJob(me.orgIds, id);
  const must: Record<string, number | null> = {};
  const nice: string[] = [];
  const drop: string[] = [];
  const errors: Record<string, string[]> = {};
  for (const [key, value] of form) {
    if (!key.startsWith("priority:") || typeof value !== "string") continue;
    const skill = key.slice("priority:".length);
    if (value === "drop") drop.push(skill);
    else if (value === "nice") nice.push(skill);
    else {
      const bar = BarSchema.safeParse(String(form.get(`bar:${skill}`) ?? ""));
      if (bar.success) must[skill] = bar.data;
      else errors[`bar:${skill}`] = bar.error.issues.map((i) => i.message);
    }
  }
  const added = String(form.get("add") ?? "").trim();
  if (added) {
    if (form.get("addPriority") === "nice") nice.push(added);
    else must[added] = null;
  }
  // The ticked tasks (`task:<skill>:<pattern>`), for skills still must-haves after this
  // save: one made nice or dropped here takes its tasks with it.
  const tasks = form.has("tasks") ? [...form.keys()]
    .filter((k) => k.startsWith("task:"))
    .map((k) => k.split(":"))
    .filter(([, skill]) => skill in must)
    .map(([, , pattern]) => pattern) : undefined;
  if (Object.keys(errors).length) return { errors, values: typed(form) };
  try {
    await call<Job>("assess", `/v1/jobs/${encodeURIComponent(id)}`, { method: "PATCH", body: { must, nice, drop, tasks } });
  } catch (e) {
    return refused(e, form);
  }
  revalidatePath(jobPath(id));
  return { message: "Saved." };
}

export async function confirmJob(id: string): Promise<FormState> {
  const me = await requireRecruiter();
  await myJob(me.orgIds, id);
  try {
    // Who confirmed is a person, by name: the assessment module records it on the job.
    await call<Job>("assess", `/v1/jobs/${encodeURIComponent(id)}/confirm`, { body: { by: `${me.name} <${me.email}>` } });
  } catch (e) {
    return refused(e);
  }
  revalidatePath(jobPath(id));
  return undefined;
}

export async function setOpen(id: string, open: boolean): Promise<FormState> {
  const me = await requireRecruiter();
  await myJob(me.orgIds, id);
  if (open) {
    // Only a confirmed job is listed: candidates apply to requirements a person has fixed.
    let job: Job;
    try {
      job = await call<Job>("assess", `/v1/jobs/${encodeURIComponent(id)}`);
    } catch (e) {
      return refused(e);
    }
    if (job.status !== "confirmed") return { message: "Confirm the skills first." };
  }
  await db.job.update({ where: { id }, data: { open } });
  revalidatePath(jobPath(id));
  return undefined;
}

export async function sendAssessment(jobId: string, applicationId: string, _: FormState, form: FormData): Promise<FormState> {
  const me = await requireRecruiter();
  const app = await myApplication(me.orgIds, jobId, applicationId);
  if (app.decision) return { message: "Already decided." };
  const parsed = StartBySchema.safeParse({ startBy: form.get("startBy") ?? undefined });
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: typed(form) };
  let issued: { tasks: Task[]; not_assessable: string[] };
  try {
    // The job's chosen tasks; asking again returns the same ones. Each waits
    // for the candidate to press Start, until the end of the chosen day.
    issued = await call("assess", "/v1/sessions", {
      body: {
        candidate_ref: app.candidate.subjectRef, job_id: jobId, model: form.get("model") === "on",
        start_by: endOfDay(parsed.data.startBy).toISOString(),
      },
      timeoutMs: 240_000,
    });
  } catch (e) {
    return refused(e, form);
  }
  for (const t of issued.tasks) {
    await db.assessment.upsert({
      where: { id: t.session_id },
      create: { id: t.session_id, candidateId: app.candidateId, applicationId: app.id },
      update: {},
    });
  }
  if (app.status === "APPLIED") await db.application.update({ where: { id: app.id }, data: { status: "ASSESSMENT_SENT" } });
  revalidatePath(`${jobPath(jobId)}/applicants/${applicationId}`);
  return issued.not_assessable.length
    ? { message: `Sent. Not assessable (no task tests them yet): ${issued.not_assessable.join(", ")}.` }
    : { message: "Sent." };
}

export async function decide(jobId: string, applicationId: string, _: FormState, form: FormData): Promise<FormState> {
  const me = await requireRecruiter();
  const app = await myApplication(me.orgIds, jobId, applicationId);
  if (app.decision) return { message: "Already decided." };
  const parsed = DecisionSchema.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: typed(form) };
  await db.$transaction([
    db.decision.create({ data: { applicationId: app.id, decidedById: me.id, ...parsed.data } }),
    db.application.update({ where: { id: app.id }, data: { status: "DECIDED" } }),
  ]);
  revalidatePath(`${jobPath(jobId)}/applicants/${applicationId}`);
  return undefined;
}
