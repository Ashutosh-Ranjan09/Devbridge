import "server-only";

import type { CurrentUser } from "./auth";
import { db } from "./db";
import { call, ServiceError } from "./services";
import type { InboxRow, Side, ThreadView } from "./types";

/** Chat between a candidate and the recruiters of the company they applied to: one thread
 * per application, opened by a recruiter. Messages live in the chat module, sealed; this
 * app checks who is on a thread, and sends only user ids. */

/** Who is on an application's thread, for the names beside each message. */
const PEOPLE = {
  candidate: { include: { user: { select: { id: true, name: true } } } },
  job: { include: { org: { include: { members: { include: { user: { select: { id: true, name: true } } } } } } } },
} as const;

/** The application behind a chat, if this person is on it: the candidate who applied, or
 * a recruiter of the job's company. Anyone else, admins included, gets null, which every
 * caller turns into the same 404 as a thread that does not exist. */
export async function threadFor(user: Pick<CurrentUser, "id" | "role">, appId: string) {
  if (user.role === "CANDIDATE") {
    return db.application.findFirst({ where: { id: appId, candidateId: user.id }, include: PEOPLE });
  }
  if (user.role === "RECRUITER") {
    return db.application.findFirst({
      where: { id: appId, job: { org: { members: { some: { userId: user.id } } } } }, include: PEOPLE,
    });
  }
  return null;
}

export type ChatApplication = NonNullable<Awaited<ReturnType<typeof threadFor>>>;

export const sideOf = (user: Pick<CurrentUser, "role">): Side => (user.role === "CANDIDATE" ? "candidate" : "recruiter");

/** user id → how the other side sees them: a recruiter with their company. */
export function namesOn(app: ChatApplication): Record<string, string> {
  const names: Record<string, string> = { [app.candidate.user.id]: app.candidate.user.name };
  for (const m of app.job.org.members) names[m.user.id] = `${m.user.name} · ${app.job.org.name}`;
  return names;
}

/** The thread, or null when no recruiter has opened it. */
export async function threadView(appId: string): Promise<ThreadView | null> {
  try {
    return await call<ThreadView>("chat", `/v1/threads/${encodeURIComponent(appId)}`);
  } catch (e) {
    if (e instanceof ServiceError && e.status === 404) return null;
    throw e;
  }
}

/** This person's threads, newest first, each with its application. A thread whose
 * application this app does not know is left out. Five seconds at most: the header asks
 * on every page, and a chat module that hangs must not hold it. */
export async function inboxFor(user: Pick<CurrentUser, "id" | "role">) {
  let rows: InboxRow[];
  if (user.role === "CANDIDATE") {
    rows = await call<InboxRow[]>("chat", `/v1/inbox?reader=${encodeURIComponent(user.id)}&candidate=${encodeURIComponent(user.id)}`, { timeoutMs: 5_000 });
  } else if (user.role === "RECRUITER") {
    const orgs = (await db.membership.findMany({ where: { userId: user.id } })).map((m) => m.orgId);
    if (!orgs.length) return [];
    const q = orgs.map((o) => `org=${encodeURIComponent(o)}`).join("&");
    rows = await call<InboxRow[]>("chat", `/v1/inbox?reader=${encodeURIComponent(user.id)}&${q}`, { timeoutMs: 5_000 });
  } else {
    return [];
  }
  const apps = await db.application.findMany({
    where: { id: { in: rows.map((r) => r.thread_id) } },
    include: { job: { include: { org: true } }, candidate: { include: { user: { select: { name: true } } } } },
  });
  const byId = new Map(apps.map((a) => [a.id, a]));
  return rows.flatMap((r) => {
    const app = byId.get(r.thread_id);
    return app ? [{ ...r, app }] : [];
  });
}

/** Unread messages across this person's threads; null when the chat module is not answering,
 * so the header shows nothing rather than failing the page. */
export async function unreadFor(user: Pick<CurrentUser, "id" | "role">): Promise<number | null> {
  if (user.role === "ADMIN") return null;
  try {
    return (await inboxFor(user)).reduce((n, r) => n + r.unread, 0);
  } catch (e) {
    if (e instanceof ServiceError) return null;
    throw e;
  }
}

export const messagesPath = (user: Pick<CurrentUser, "role">) =>
  user.role === "CANDIDATE" ? "/candidate/messages" : "/recruiter/messages";
