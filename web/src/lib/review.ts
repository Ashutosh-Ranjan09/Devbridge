import "server-only";

import { db } from "./db";
import type { Report } from "./types";

export type Bucket = keyof Report["findings"]["buckets"];
export type MarkView = { mark: "VERIFIED" | "UNVERIFIED"; note: string; by: string; at: Date };
export type Marks = Map<string, MarkView>;

/** A line of M5's report: a finding by its id, any other line by its place in the bucket. */
export const lineKey = (bucket: Bucket, at: number | string) => `${bucket}:${at}`;

/** Every line of one report an admin can mark: the action refuses any other key. */
export function lineKeys(report: Report): Set<string> {
  const b = report.findings.buckets;
  return new Set([
    ...b.verified.map((_, i) => lineKey("verified", i)),
    ...b.contradicted.map((id) => lineKey("contradicted", id)),
    ...b.needs_context.map((id) => lineKey("needs_context", id)),
    ...b.not_evaluated.map((_, i) => lineKey("not_evaluated", i)),
    ...b.out_of_scope.map((_, i) => lineKey("out_of_scope", i)),
  ]);
}

/** The newest mark on each line. `names` only in the admin area; elsewhere "an admin". */
export async function marksFor(verificationId: string, { names = false } = {}): Promise<Marks> {
  const rows = await db.itemReview.findMany({
    where: { verificationId },
    orderBy: { id: "desc" },
    select: { itemKey: true, mark: true, note: true, createdAt: true, reviewedBy: { select: { name: true } } },
  });
  const out: Marks = new Map();
  for (const r of rows) {
    if (!out.has(r.itemKey)) {
      out.set(r.itemKey, { mark: r.mark, note: r.note, at: r.createdAt, by: names ? r.reviewedBy.name : "an admin" });
    }
  }
  return out;
}
