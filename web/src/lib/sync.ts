import "server-only";

import { db } from "./db";
import { call } from "./services";
import type { Report } from "./types";

/** Handing evidence to M6. The web layer moves each document unchanged; M6 decides
 * what it is worth. Both ingests are idempotent in M6 (a batch seen before is reported
 * as a duplicate), so a retry after a failure, or two at once, records nothing twice.
 * `sentToM6At` only stops asking again once M6 has said yes. */

export async function forwardReport(id: string, report: Report): Promise<void> {
  if (report.status === "failed") return; // nothing was verified, so nothing to project
  await call("m6", "/evidence/report", { body: report });
  await db.verification.update({ where: { id }, data: { sentToM6At: new Date() } });
}

export async function forwardAssessment(id: string): Promise<void> {
  const batch = await call("assess", `/v1/sessions/${encodeURIComponent(id)}/events`);
  await call("m6", "/evidence/batch", { body: batch });
  await db.assessment.update({ where: { id }, data: { sentToM6At: new Date() } });
}

/** A task's result is final: the recruiter's to read, and M6's evidence. Before that
 * the candidate may still change it, so neither hears of an attempt. Called by the
 * action that made it final, and by the pages, for a task the deadline made final. */
export async function settleAssessment(id: string): Promise<void> {
  const row = await db.assessment.findUniqueOrThrow({ where: { id } });
  if (row.applicationId) {
    await db.application.updateMany({
      where: { id: row.applicationId, status: "ASSESSMENT_SENT" },
      data: { status: "SUBMITTED" },
    });
  }
  // The result is stored by the assessment module either way; if M6 is down, the
  // skills page tries again later.
  if (!row.sentToM6At) await forwardAssessment(id).catch(() => {});
}

/** Everything of this candidate's that M6 has not accepted yet. Run after a response
 * (`after()`), so a module that is down delays the evidence, never the page. */
export async function forwardPending(candidateId: string): Promise<void> {
  const [verifications, assessments] = await Promise.all([
    db.verification.findMany({ where: { candidateId, sentToM6At: null } }),
    db.assessment.findMany({ where: { candidateId, sentToM6At: null } }),
  ]);
  for (const v of verifications) {
    const report = await call<Report | { status: "running" }>("m5", `/v1/verifications/${encodeURIComponent(v.id)}`)
      .catch(() => null);
    if (report && report.status !== "running") await forwardReport(v.id, report as Report).catch(() => {});
  }
  for (const a of assessments) {
    // Only a final result exists here: attempts still open stay with the candidate.
    const result = await call("assess", `/v1/sessions/${encodeURIComponent(a.id)}/result`).catch(() => null);
    if (result) await settleAssessment(a.id).catch(() => {});
  }
}
