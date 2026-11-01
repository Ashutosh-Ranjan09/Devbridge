import "server-only";

import type { CurrentUser } from "./auth";
import { db } from "./db";

/** Who may open a candidate's CV and proofs: the candidate, an admin, or a recruiter
 * whose organisation's job they applied to (as on the applicant page). Anyone else gets
 * the same "not found" as a file that does not exist. */
export async function mayReadFilesOf(user: CurrentUser, candidateId: string): Promise<boolean> {
  if (user.role === "ADMIN") return true;
  if (user.role === "CANDIDATE") return user.id === candidateId;
  const applied = await db.application.count({
    where: { candidateId, job: { org: { members: { some: { userId: user.id } } } } },
  });
  return applied > 0;
}
