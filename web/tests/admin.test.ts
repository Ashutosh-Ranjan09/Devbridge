/** An admin marks lines of a candidate's CV report, with M5 faked at fetch. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { form, jar, redirectOf, resetDb } from "./next";

const { markLine } = await import("@/app/admin/actions");
const { db } = await import("@/lib/db");
const { marksFor } = await import("@/lib/review");
const { createSession } = await import("@/lib/session");

const REPORT = {
  verification_id: "v_1",
  status: "completed",
  findings: {
    discrepancies: [],
    buckets: {
      verified: ["Codeforces peak rating 1495 - matches API exactly"],
      contradicted: ["f01"],
      needs_context: [],
      not_evaluated: ["GitHub account ownership - not proven"],
      out_of_scope: ["CGPA 9.34 - self-declared"],
    },
  },
};

let fetched: string[] = [];
function m5(status = 200, body: unknown = REPORT) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    fetched.push(url);
    return new Response(JSON.stringify(body), { status });
  }));
}

const as = async (userId: string) => {
  jar.clear();
  await createSession(userId);
};

async function user(email: string, role: "ADMIN" | "CANDIDATE", name: string, subjectRef?: string) {
  const u = await db.user.create({
    data: { email, name, passwordHash: "x", role, ...(subjectRef ? { candidate: { create: { subjectRef } } } : {}) },
  });
  return u.id;
}

let admin: string;
let asha: string;
beforeEach(async () => {
  fetched = [];
  await resetDb();
  admin = await user("meera@devbridge.example", "ADMIN", "Meera Admin");
  asha = await user("asha@example.com", "CANDIDATE", "Asha Rao", "subj_asha");
  await db.verification.create({ data: { id: "v_1", candidateId: asha, fileName: "asha.pdf" } });
  await as(admin);
  m5();
});
afterEach(() => vi.unstubAllGlobals());

const mark = (key: string, fields: Record<string, string>, userId = asha, verificationId = "v_1") =>
  markLine(userId, verificationId, key, undefined, form(fields));

describe("marking a line", () => {
  it("only an admin can mark", async () => {
    await as(asha);
    const to = await redirectOf(mark("not_evaluated:0", { mark: "VERIFIED", note: "Saw the account settings page" }));
    expect(to).toBe("/candidate");
    expect(await db.itemReview.count()).toBe(0);
  });

  it("a short note is refused, and what was typed comes back", async () => {
    const state = await mark("not_evaluated:0", { mark: "VERIFIED", note: "ok" });
    expect(state?.errors?.note).toBeDefined();
    expect(state?.values).toEqual({ mark: "VERIFIED", note: "ok" });
    expect(fetched).toEqual([]); // refused before M5 is asked
  });

  it("a line that is not in the report is refused", async () => {
    const state = await mark("not_evaluated:7", { mark: "VERIFIED", note: "Saw the account settings page" });
    expect(state?.message).toMatch(/not in this report/);
    expect(fetched).toEqual(["http://m5.test/v1/verifications/v_1"]);
    expect(await db.itemReview.count()).toBe(0);
  });

  it("another candidate's report is refused", async () => {
    const ravi = await user("ravi@example.com", "CANDIDATE", "Ravi K", "subj_ravi");
    const state = await mark("verified:0", { mark: "UNVERIFIED", note: "The handle belongs to someone else" }, ravi);
    expect(state?.message).toMatch(/No such report/);
    expect(await db.itemReview.count()).toBe(0);
  });

  it("marking again makes the newer mark current, and keeps the old one", async () => {
    expect((await mark("contradicted:f01", { mark: "UNVERIFIED", note: "Confirmed with the contest page" }))?.message).toBe("Marked.");
    await mark("contradicted:f01", { mark: "VERIFIED", note: "The candidate showed a later rating" });
    const marks = await marksFor("v_1", { names: true });
    expect(marks.get("contradicted:f01")).toMatchObject({ mark: "VERIFIED", note: "The candidate showed a later rating", by: "Meera Admin" });
    expect(await db.itemReview.count()).toBe(2);
  });

  it("outside the admin area the mark says an admin made it, not who", async () => {
    await mark("out_of_scope:0", { mark: "VERIFIED", note: "Saw the official transcript" });
    expect((await marksFor("v_1")).get("out_of_scope:0")?.by).toBe("an admin");
  });
});
