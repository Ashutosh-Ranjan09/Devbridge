import { beforeEach, describe, expect, it } from "vitest";

import { resetDb } from "./next";

const { mayReadFilesOf } = await import("@/lib/access");
const { db } = await import("@/lib/db");

const as = (id: string, role: "CANDIDATE" | "RECRUITER" | "ADMIN") => ({ id, name: "x", email: `${id}@example.com`, role });

async function user(id: string, role: "CANDIDATE" | "RECRUITER" | "ADMIN") {
  await db.user.create({
    data: { id, email: `${id}@example.com`, name: id, passwordHash: "x", role,
      ...(role === "CANDIDATE" ? { candidate: { create: { subjectRef: `subject:${id}` } } } : {}) },
  });
}

beforeEach(async () => {
  await resetDb();
  await user("asha", "CANDIDATE");
  await user("ravi", "CANDIDATE");
  await user("rec", "RECRUITER");
  await user("other", "RECRUITER");
  await user("adm", "ADMIN");
  await db.organisation.create({ data: { id: "org", name: "Acme", kind: "ENTERPRISE", members: { create: [{ userId: "rec" }] } } });
  await db.organisation.create({ data: { id: "org2", name: "Else", kind: "ENTERPRISE", members: { create: [{ userId: "other" }] } } });
  await db.job.create({ data: { id: "job", title: "Dev", orgId: "org", createdById: "rec", open: true } });
});

describe("who may open a candidate's CV and proofs", () => {
  it("the candidate, and no other candidate", async () => {
    expect(await mayReadFilesOf(as("asha", "CANDIDATE"), "asha")).toBe(true);
    expect(await mayReadFilesOf(as("ravi", "CANDIDATE"), "asha")).toBe(false);
  });

  it("a recruiter only once the candidate applied to their organisation's job", async () => {
    expect(await mayReadFilesOf(as("rec", "RECRUITER"), "asha")).toBe(false);
    await db.application.create({ data: { jobId: "job", candidateId: "asha" } });
    expect(await mayReadFilesOf(as("rec", "RECRUITER"), "asha")).toBe(true);
    expect(await mayReadFilesOf(as("other", "RECRUITER"), "asha")).toBe(false);
  });

  it("an admin", async () => {
    expect(await mayReadFilesOf(as("adm", "ADMIN"), "asha")).toBe(true);
  });
});
