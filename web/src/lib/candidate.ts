import "server-only";

import { notFound } from "next/navigation";

import { requireRole } from "./auth";
import { db } from "./db";

/** The signed-in candidate and the subject_ref the modules know them by. */
export async function requireCandidate() {
  const user = await requireRole("CANDIDATE");
  const { subjectRef } = await db.candidate.findUniqueOrThrow({ where: { userId: user.id } });
  return { ...user, subjectRef };
}

/** A verification of THIS candidate, or 404. The same 404 for another candidate's id
 * as for an id that does not exist, so ids cannot be probed. */
export async function myVerification(candidateId: string, id: string) {
  return (await db.verification.findFirst({ where: { id, candidateId } })) ?? notFound();
}

/** The job and company that sent a task; none for practice. */
export const TASK_JOB = { application: { select: { job: { select: { id: true, title: true, org: { select: { name: true } } } } } } } as const;

export async function myAssessment(candidateId: string, id: string) {
  return (await db.assessment.findFirst({ where: { id, candidateId }, include: TASK_JOB })) ?? notFound();
}

/** Who a task is for: the company and job that sent it, or the candidate's own practice. */
export function taskFor(job: { title: string; org: { name: string } } | null | undefined): string {
  return job ? `${job.org.name} · ${job.title}` : "Practice";
}
