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

export async function myAssessment(candidateId: string, id: string) {
  return (await db.assessment.findFirst({ where: { id, candidateId } })) ?? notFound();
}
