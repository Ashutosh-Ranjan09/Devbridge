import "server-only";

import { notFound } from "next/navigation";

import { requireRole } from "./auth";
import { db } from "./db";

/** The signed-in recruiter and the organisations they hire for. */
export async function requireRecruiter() {
  const user = await requireRole("RECRUITER");
  const memberships = await db.membership.findMany({ where: { userId: user.id }, include: { org: true } });
  return { ...user, orgs: memberships.map((m) => m.org), orgIds: memberships.map((m) => m.orgId) };
}

/** A job of one of THEIR organisations, or 404 — the same 404 as a job that does not exist. */
export async function myJob(orgIds: string[], id: string) {
  return (await db.job.findFirst({ where: { id, orgId: { in: orgIds } }, include: { org: true } })) ?? notFound();
}

/** An application to one of their jobs, with the candidate, or 404. A recruiter reaches a
 * candidate only through an application to their own job. */
export async function myApplication(orgIds: string[], jobId: string, id: string) {
  return (
    (await db.application.findFirst({
      where: { id, jobId, job: { orgId: { in: orgIds } } },
      include: { candidate: { include: { user: true } }, decision: { include: { decidedBy: true } }, job: true },
    })) ?? notFound()
  );
}
