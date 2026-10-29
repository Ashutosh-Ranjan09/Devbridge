/** Sign-up, login, sessions and roles, against a real (temporary) database. */

import { beforeEach, describe, expect, it } from "vitest";

import { form, jar, redirectOf } from "./next";

const { login, logout, signup } = await import("@/app/(auth)/actions");
const { currentUser, requireRole } = await import("@/lib/auth");
const { SESSION_COOKIE } = await import("@/lib/cookie");
const { db } = await import("@/lib/db");
const { hashToken } = await import("@/lib/session");

const PASSWORD = "correct horse battery";
const candidate = (email = "asha@example.com") =>
  form({ role: "CANDIDATE", name: "Asha Rao", email, password: PASSWORD });
const recruiter = (extra: Record<string, string> = {}) =>
  form({ role: "RECRUITER", name: "Ravi Iyer", email: "ravi@example.com", password: PASSWORD,
         orgName: "PayFlow", orgKind: "ENTERPRISE", ...extra });

beforeEach(async () => {
  jar.clear();
  await db.session.deleteMany();
  await db.membership.deleteMany();
  await db.organisation.deleteMany();
  await db.candidate.deleteMany();
  await db.user.deleteMany();
});

describe("signing up", () => {
  it("a candidate gets a session and a pseudonymous subject_ref", async () => {
    expect(await redirectOf(signup(undefined, candidate()))).toBe("/candidate");
    const user = await db.user.findUniqueOrThrow({ where: { email: "asha@example.com" }, include: { candidate: true } });
    expect(user.role).toBe("CANDIDATE");
    expect(user.candidate?.subjectRef).toMatch(/^subject:[0-9a-f]{16}$/);
    expect(user.candidate?.subjectRef).not.toContain("asha");
    expect(jar.has(SESSION_COOKIE)).toBe(true);
  });

  it("stores a bcrypt hash, never the password", async () => {
    await redirectOf(signup(undefined, candidate()));
    const user = await db.user.findUniqueOrThrow({ where: { email: "asha@example.com" } });
    expect(user.passwordHash).toMatch(/^\$2[aby]\$12\$/);
    expect(user.passwordHash).not.toContain(PASSWORD);
  });

  it("an email is one account, whatever its case", async () => {
    await redirectOf(signup(undefined, candidate()));
    const state = await signup(undefined, candidate("  ASHA@Example.com "));
    expect(state?.errors?.email?.[0]).toMatch(/exists/);
  });

  it("a recruiter names an organisation, and becomes its member", async () => {
    expect((await signup(undefined, recruiter({ orgName: "" })))?.errors?.orgName).toBeDefined();
    expect(await redirectOf(signup(undefined, recruiter()))).toBe("/recruiter");
    const m = await db.membership.findFirstOrThrow({ include: { org: true, user: true } });
    expect([m.user.email, m.org.name, m.org.kind]).toEqual(["ravi@example.com", "PayFlow", "ENTERPRISE"]);
  });

  it("nobody signs up as an admin", async () => {
    const state = await signup(undefined, form({ role: "ADMIN", name: "Eve", email: "eve@example.com", password: PASSWORD }));
    expect(state?.errors?.role).toBeDefined();
    expect(await db.user.count()).toBe(0);
  });

  it("a refused form keeps what was typed, except the password", async () => {
    const state = await signup(undefined, form({ role: "CANDIDATE", name: "A", email: "asha@example.com", password: PASSWORD }));
    expect(state?.values?.email).toBe("asha@example.com");
    expect(JSON.stringify(state)).not.toContain(PASSWORD);
  });
});

describe("logging in", () => {
  beforeEach(async () => {
    await redirectOf(signup(undefined, candidate()));
    jar.clear();
  });

  it("goes to the role's home", async () => {
    expect(await redirectOf(login(undefined, form({ email: "Asha@example.com", password: PASSWORD })))).toBe("/candidate");
    expect((await currentUser())?.email).toBe("asha@example.com");
  });

  it("says the same for a wrong password and an unknown email", async () => {
    const wrong = await login(undefined, form({ email: "asha@example.com", password: "not it at all" }));
    const unknown = await login(undefined, form({ email: "nobody@example.com", password: PASSWORD }));
    expect(wrong?.message).toBe("Email or password is wrong.");
    expect(unknown?.message).toBe(wrong?.message);
    expect(jar.has(SESSION_COOKIE)).toBe(false);
  });
});

describe("sessions", () => {
  it("the database holds the token's hash, not the token", async () => {
    await redirectOf(signup(undefined, candidate()));
    const token = jar.get(SESSION_COOKIE)!;
    const rows = await db.session.findMany();
    expect(rows.map((r) => r.tokenHash)).toEqual([hashToken(token)]);
    expect(rows[0].tokenHash).not.toBe(token);
  });

  it("an expired session signs nobody in, and is removed", async () => {
    await redirectOf(signup(undefined, candidate()));
    await db.session.updateMany({ data: { expiresAt: new Date(Date.now() - 1000) } });
    expect(await currentUser()).toBeNull();
    expect(await db.session.count()).toBe(0);
  });

  it("an unknown cookie signs nobody in", async () => {
    jar.set(SESSION_COOKIE, "made-up");
    expect(await currentUser()).toBeNull();
  });

  it("logging out ends the session in the database, not only the cookie", async () => {
    await redirectOf(signup(undefined, candidate()));
    expect(await redirectOf(logout())).toBe("/login");
    expect(jar.has(SESSION_COOKIE)).toBe(false);
    expect(await db.session.count()).toBe(0);
  });
});

describe("roles", () => {
  it("signed out goes to /login", async () => {
    expect(await redirectOf(requireRole("CANDIDATE"))).toBe("/login");
  });

  it("another role's page sends you to your own home", async () => {
    await redirectOf(signup(undefined, candidate()));
    expect(await redirectOf(requireRole("RECRUITER"))).toBe("/candidate");
    expect(await redirectOf(requireRole("ADMIN"))).toBe("/candidate");
    expect((await requireRole("CANDIDATE")).email).toBe("asha@example.com");
  });
});
