/** Sign-up, login, sessions and roles, against a real (temporary) database. */

import { beforeEach, describe, expect, it } from "vitest";

import { form, jar, redirectOf, resetDb } from "./next";

const { login, logout, resetPassword, signup } = await import("@/app/(auth)/actions");
const { makeResetLink } = await import("@/app/admin/actions");
const { changePassword } = await import("@/app/account/actions");
const { currentUser, requireRole } = await import("@/lib/auth");
const { SESSION_COOKIE } = await import("@/lib/cookie");
const { db } = await import("@/lib/db");
const { createSession, hashToken } = await import("@/lib/session");
const { MAX_FAILURES, WINDOW_MS, recordFailure } = await import("@/lib/limits");

const PASSWORD = "correct horse battery";
const candidate = (email = "asha@example.com") =>
  form({ role: "CANDIDATE", name: "Asha Rao", email, password: PASSWORD });
const recruiter = (extra: Record<string, string> = {}) =>
  form({ role: "RECRUITER", name: "Ravi Iyer", email: "ravi@example.com", password: PASSWORD,
         orgName: "PayFlow", orgKind: "ENTERPRISE", ...extra });

beforeEach(async () => {
  jar.clear();
  await resetDb();
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

describe("too many wrong attempts", () => {
  const attempt = (email: string, password: string) => login(undefined, form({ email, password }));
  const wrongTimes = async (email: string, n = MAX_FAILURES) => {
    for (let i = 0; i < n; i++) await attempt(email, "not it at all");
  };

  beforeEach(async () => {
    await redirectOf(signup(undefined, candidate()));
    jar.clear();
  });

  it("five wrong passwords lock the email, even against the right one", async () => {
    await wrongTimes("asha@example.com");
    const state = await attempt("asha@example.com", PASSWORD);
    expect(state?.message).toBe("Too many wrong attempts for this email. Try again in 15 minutes.");
    expect(state?.values).toEqual({ email: "asha@example.com" });
    expect(jar.has(SESSION_COOKIE)).toBe(false);
  });

  it("an email with no account locks the same way, so the lock says nothing about accounts", async () => {
    await wrongTimes("asha@example.com");
    await wrongTimes("nobody@example.com");
    const a = await attempt("asha@example.com", PASSWORD);
    const b = await attempt("nobody@example.com", PASSWORD);
    expect(b?.message).toBe(a?.message);
  });

  it("attempts older than the window no longer count", async () => {
    const long = new Date(Date.now() - WINDOW_MS - 1000);
    for (let i = 0; i < MAX_FAILURES; i++) await recordFailure("asha@example.com", long);
    expect(await redirectOf(attempt("asha@example.com", PASSWORD))).toBe("/candidate");
  });

  it("a successful login clears the count", async () => {
    await wrongTimes("asha@example.com", MAX_FAILURES - 1);
    await redirectOf(attempt("asha@example.com", PASSWORD));
    jar.clear();
    await wrongTimes("asha@example.com", MAX_FAILURES - 1);
    expect(await redirectOf(attempt("asha@example.com", PASSWORD))).toBe("/candidate");
    expect(await db.loginFailure.count()).toBe(0);
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

describe("a password reset link", () => {
  const NEW = "a brand new passphrase";
  let asha: string;
  let admin: string;

  /** The admin makes a link; the token is its last path segment. */
  async function link(userId = asha): Promise<string> {
    jar.clear();
    await createSession(admin);
    const made = await makeResetLink(userId);
    jar.clear();
    expect(made.link).toMatch(/^http:\/\/web\.test\/reset\/[\w-]{43}$/);
    return made.link!.split("/").pop()!;
  }
  const reset = (token: string, password = NEW) => resetPassword(token, undefined, form({ password }));

  beforeEach(async () => {
    await redirectOf(signup(undefined, candidate()));
    asha = (await db.user.findUniqueOrThrow({ where: { email: "asha@example.com" } })).id;
    admin = (await db.user.create({ data: { email: "meera@example.com", name: "Meera", passwordHash: "x", role: "ADMIN" } })).id;
    jar.clear();
  });

  it("only an admin can make one, and never for their own account", async () => {
    await createSession(asha);
    await expect(redirectOf(makeResetLink(asha))).resolves.toBe("/candidate");
    jar.clear();
    await createSession(admin);
    expect((await makeResetLink(admin)).message).toMatch(/your own account/);
    expect(await db.passwordReset.count()).toBe(0);
  });

  it("stores the token's hash, never the token", async () => {
    const token = await link();
    const row = await db.passwordReset.findFirstOrThrow();
    expect(row.tokenHash).toBe(hashToken(token));
    expect(row.tokenHash).not.toContain(token);
  });

  it("sets the password, logs the person in, and works once", async () => {
    const token = await link();
    expect(await redirectOf(reset(token))).toBe("/candidate");
    expect((await currentUser())?.email).toBe("asha@example.com");
    jar.clear();
    expect(await redirectOf(login(undefined, form({ email: "asha@example.com", password: NEW })))).toBe("/candidate");
    jar.clear();
    expect((await reset(token, "yet another passphrase"))?.message).toMatch(/expired or was already used/);
  });

  it("an expired link and a made-up token get the same answer", async () => {
    const token = await link();
    await db.passwordReset.updateMany({ data: { expiresAt: new Date(Date.now() - 1000) } });
    const expired = await reset(token);
    const madeUp = await reset("x".repeat(43));
    expect(expired?.message).toMatch(/expired or was already used/);
    expect(madeUp?.message).toBe(expired?.message);
  });

  it("a new link cancels the one before it", async () => {
    const first = await link();
    const second = await link();
    expect((await reset(first))?.message).toMatch(/expired or was already used/);
    expect(await redirectOf(reset(second))).toBe("/candidate");
  });

  it("ends the person's other sessions and clears their failed logins", async () => {
    await createSession(asha);
    jar.clear();
    await recordFailure("asha@example.com");
    const token = await link();
    await redirectOf(reset(token));
    expect(await db.session.count({ where: { userId: asha } })).toBe(1); // only the one just made
    expect(await db.loginFailure.count()).toBe(0);
  });

  it("a short password is refused and the link stays usable", async () => {
    const token = await link();
    expect((await reset(token, "short"))?.errors?.password).toBeDefined();
    expect(await redirectOf(reset(token))).toBe("/candidate");
  });
});

describe("changing your password", () => {
  const NEW = "a brand new passphrase";
  const change = (current: string, password = NEW) => changePassword(undefined, form({ current, password }));

  beforeEach(async () => {
    await redirectOf(signup(undefined, candidate())); // signed in as Asha
  });

  it("needs the current password, and keeps this session while ending the others", async () => {
    const asha = (await db.user.findUniqueOrThrow({ where: { email: "asha@example.com" } })).id;
    const here = jar.get(SESSION_COOKIE)!;
    await createSession(asha); // another device
    jar.set(SESSION_COOKIE, here);
    expect((await change(PASSWORD))?.message).toMatch(/Password changed/);
    expect(await db.session.count({ where: { userId: asha } })).toBe(1);
    expect((await currentUser())?.email).toBe("asha@example.com"); // still signed in here
    jar.clear();
    expect(await redirectOf(login(undefined, form({ email: "asha@example.com", password: NEW })))).toBe("/candidate");
  });

  it("a wrong current password is refused and counts against the login limit", async () => {
    expect((await change("not it at all"))?.errors?.current).toEqual(["That is not your current password."]);
    expect(await db.loginFailure.count({ where: { email: "asha@example.com" } })).toBe(1);
    for (let i = 1; i < MAX_FAILURES; i++) await change("not it at all");
    expect((await change(PASSWORD))?.message).toMatch(/Too many wrong attempts/);
  });

  it("the new password follows the signup rule", async () => {
    expect((await change(PASSWORD, "short"))?.errors?.password).toBeDefined();
  });

  it("signed out, there is no account to change", async () => {
    jar.clear();
    expect(await redirectOf(change(PASSWORD))).toBe("/login");
  });
});
