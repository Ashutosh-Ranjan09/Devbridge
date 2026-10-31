import "server-only";

import { createHash, randomBytes } from "node:crypto";

import { cookies } from "next/headers";
import { connection } from "next/server";

import { SESSION_COOKIE } from "./cookie";
import { db } from "./db";

const LIFETIME_MS = 7 * 24 * 60 * 60 * 1000;

/** What the database stores for a token. A copy of the database cannot be turned back
 * into a cookie that signs anyone in. */
export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export async function createSession(userId: string): Promise<void> {
  const token = randomBytes(32).toString("base64url");
  const expiresAt = new Date(Date.now() + LIFETIME_MS);
  await db.session.create({ data: { tokenHash: hashToken(token), userId, expiresAt } });
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true, // no script on the page can read it
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax", // not sent on cross-site POSTs
    path: "/",
    expires: expiresAt,
  });
}

/** The user id behind this request's cookie, or null. An expired session is removed. */
export async function sessionUserId(): Promise<string | null> {
  // A session is decided at request time, never in a prerender: Next 16 prefetches
  // linked pages by prerendering them, and refuses the `new Date()` below there.
  // Prefetches stop here, at the static shell, which is right for signed-in content.
  await connection();
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return null;
  const session = await db.session.findUnique({ where: { tokenHash: hashToken(token) } });
  if (!session) return null;
  if (session.expiresAt <= new Date()) {
    await db.session.deleteMany({ where: { tokenHash: session.tokenHash } });
    return null;
  }
  return session.userId;
}

/** Every session of this user but the one making this request: after a password
 * change, any other device has to log in again with the new one. */
export async function endOtherSessions(userId: string): Promise<void> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  await db.session.deleteMany({ where: { userId, NOT: { tokenHash: hashToken(token ?? "") } } });
}

export async function deleteSession(): Promise<void> {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;
  if (token) await db.session.deleteMany({ where: { tokenHash: hashToken(token) } });
  store.delete(SESSION_COOKIE);
}
