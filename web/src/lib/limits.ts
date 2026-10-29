import "server-only";

import { db } from "./db";

export const MAX_FAILURES = 5;
export const WINDOW_MS = 15 * 60 * 1000;

/** Whole minutes until this email may try again; 0 when it may now. */
export async function lockedFor(email: string, now = new Date()): Promise<number> {
  const recent = await db.loginFailure.findMany({
    where: { email, at: { gte: new Date(now.getTime() - WINDOW_MS) } },
    orderBy: { at: "asc" },
    select: { at: true },
  });
  if (recent.length < MAX_FAILURES) return 0;
  const freeAt = recent[recent.length - MAX_FAILURES].at.getTime() + WINDOW_MS;
  return Math.max(1, Math.ceil((freeAt - now.getTime()) / 60_000));
}

/** One more wrong attempt; this email's attempts older than the window go. */
export async function recordFailure(email: string, now = new Date()): Promise<void> {
  await db.$transaction([
    db.loginFailure.create({ data: { email, at: now } }),
    db.loginFailure.deleteMany({ where: { email, at: { lt: new Date(now.getTime() - WINDOW_MS) } } }),
  ]);
}

export async function clearFailures(email: string): Promise<void> {
  await db.loginFailure.deleteMany({ where: { email } });
}
