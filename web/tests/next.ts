import { vi } from "vitest";

/** Next's request APIs, faked: a cookie jar, and `redirect` as the throw it really is. */

export const jar = new Map<string, string>();

export class Redirect extends Error {
  constructor(readonly to: string) {
    super(`redirect to ${to}`);
  }
}

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (jar.has(name) ? { name, value: jar.get(name)! } : undefined),
    has: (name: string) => jar.has(name),
    set: (name: string, value: string) => void jar.set(name, value),
    delete: (name: string) => void jar.delete(name),
  }),
  headers: async () => new Headers({ host: "web.test" }),
}));

vi.mock("next/server", async (original) => ({
  ...(await original<typeof import("next/server")>()),
  connection: async () => {}, // every test is a request
}));

vi.mock("next/cache", () => ({
  revalidatePath: () => {}, // re-renders a page for the browser; there is none here
}));

export class NotFound extends Error {}

vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Redirect(to);
  },
  notFound: () => {
    throw new NotFound("not found");
  },
}));

/** Where an action sent the browser. Fails if it returned instead. */
export async function redirectOf(run: Promise<unknown>): Promise<string> {
  try {
    await run;
  } catch (e) {
    if (e instanceof Redirect) return e.to;
    throw e;
  }
  throw new Error("expected a redirect; the action returned");
}

export function form(fields: Record<string, string>): FormData {
  const f = new FormData();
  for (const [k, v] of Object.entries(fields)) f.set(k, v);
  return f;
}

/** Every table emptied, children first. One list, so a new table is added in one place. */
export async function resetDb(): Promise<void> {
  const { db } = await import("@/lib/db");
  await db.loginFailure.deleteMany();
  await db.passwordReset.deleteMany();
  await db.itemReview.deleteMany();
  await db.proof.deleteMany();
  await db.decision.deleteMany();
  await db.assessment.deleteMany();
  await db.application.deleteMany();
  await db.job.deleteMany();
  await db.verification.deleteMany();
  await db.session.deleteMany();
  await db.membership.deleteMany();
  await db.organisation.deleteMany();
  await db.candidate.deleteMany();
  await db.user.deleteMany();
}
