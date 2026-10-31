/** Jobs, applicants, assessments sent and decisions, with the modules faked at fetch. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { form, jar, NotFound, redirectOf, resetDb } from "./next";

const { confirmJob, createJob, decide, editJob, sendAssessment, setOpen } = await import("@/app/recruiter/actions");
const { applyToJob, submitSolution } = await import("@/app/candidate/actions");
const { db } = await import("@/lib/db");
const { myApplication, myJob } = await import("@/lib/recruiter");
const { createSession } = await import("@/lib/session");
const { dayIn, endOfDay } = await import("@/lib/tasks");

type Sent = { url: string; method: string; body: unknown };
let sent: Sent[] = [];

function modules(routes: Record<string, [number, unknown]>) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    sent.push({ url, method, body: typeof init.body === "string" ? JSON.parse(init.body) : init.body });
    const hit = Object.entries(routes).find(([k]) => {
      const [m, prefix] = k.split(" ");
      return m === method && url.startsWith(prefix);
    });
    if (!hit) throw new TypeError(`fetch failed: ${method} ${url}`);
    return new Response(JSON.stringify(hit[1][1]), { status: hit[1][0] });
  }));
}

async function recruiter(email: string, org: string) {
  const user = await db.user.create({
    data: { email, name: `Recruiter ${org}`, passwordHash: "x", role: "RECRUITER",
            memberships: { create: { org: { create: { name: org, kind: "ENTERPRISE" } } } } },
    include: { memberships: true },
  });
  return { id: user.id, orgId: user.memberships[0].orgId };
}

async function candidate(email: string, subjectRef: string, name = "Asha Rao") {
  const user = await db.user.create({
    data: { email, name, passwordHash: "x", role: "CANDIDATE", candidate: { create: { subjectRef } } },
  });
  return user.id;
}

const as = async (userId: string) => {
  jar.clear();
  await createSession(userId);
};

const JD = "Backend Engineer. Protect our login endpoints from abuse. Strong Python and solid SQL are required.";
let ravi: { id: string; orgId: string };
beforeEach(async () => {
  sent = [];
  await resetDb();
  ravi = await recruiter("ravi@payflow.example", "PayFlow");
  await as(ravi.id);
});
afterEach(() => vi.unstubAllGlobals());

async function aJob(open = false) {
  await db.job.create({ data: { id: "job_1", title: "Backend", orgId: ravi.orgId, createdById: ravi.id, open } });
}

describe("jobs", () => {
  it("a job description becomes a job of the recruiter's organisation", async () => {
    modules({ "POST http://assess.test/v1/jobs": [201, { job_id: "job_1", status: "proposed", skills: [] }] });
    const to = await redirectOf(createJob(undefined, form({ title: "Backend", text: JD, orgId: ravi.orgId })));
    expect(to).toBe("/recruiter/jobs/job_1");
    expect(sent[0].body).toEqual({ text: JD, model: false });
    expect(await db.job.findUniqueOrThrow({ where: { id: "job_1" } })).toMatchObject({ orgId: ravi.orgId, open: false });
  });

  it("nobody files a job under another organisation", async () => {
    const other = await recruiter("x@other.example", "Other");
    modules({});
    const state = await createJob(undefined, form({ title: "Backend", text: JD, orgId: other.orgId }));
    expect(state?.errors?.orgId).toBeDefined();
    expect(sent).toEqual([]);
  });

  it("the skills table becomes one edit: musts with bars, nice-to-haves, drops, an addition", async () => {
    await aJob();
    modules({ "PATCH http://assess.test/v1/jobs/job_1": [200, {}] });
    const state = await editJob("job_1", undefined, form({
      "priority:python": "must", "bar:python": "0.4",
      "priority:sql": "must", "bar:sql": "",
      "priority:redis": "nice", "bar:redis": "",
      "priority:kafka": "drop", "bar:kafka": "",
      add: "rate_limiting", addPriority: "must",
    }));
    expect(state?.message).toBe("Saved.");
    expect(sent[0].body).toEqual({ must: { python: 0.4, sql: null, rate_limiting: null }, nice: ["redis"], drop: ["kafka"] });
  });

  it("a bar outside 0–1 is refused before anything is sent, and the other edits survive", async () => {
    await aJob();
    modules({});
    const state = await editJob("job_1", undefined, form({ "priority:python": "must", "bar:python": "5", "priority:sql": "nice" }));
    expect(state?.errors?.["bar:python"]).toBeDefined();
    // React resets the form after the action; these are what it shows again.
    expect(state?.values).toMatchObject({ "bar:python": "5", "priority:sql": "nice" });
    expect(sent).toEqual([]);
  });

  it("confirming names the person who confirmed", async () => {
    await aJob();
    modules({ "POST http://assess.test/v1/jobs/job_1/confirm": [200, {}] });
    await confirmJob("job_1");
    expect(sent[0].body).toEqual({ by: "Recruiter PayFlow <ravi@payflow.example>" });
  });

  it("only a confirmed job is opened to candidates", async () => {
    await aJob();
    modules({ "GET http://assess.test/v1/jobs/job_1": [200, { job_id: "job_1", status: "proposed" }] });
    expect((await setOpen("job_1", true))?.message).toMatch(/Confirm/);
    expect((await db.job.findUniqueOrThrow({ where: { id: "job_1" } })).open).toBe(false);
  });

  it("another organisation's job is a 404, to every action", async () => {
    await aJob();
    const other = await recruiter("x@other.example", "Other");
    await as(other.id);
    modules({});
    await expect(myJob([other.orgId], "job_1")).rejects.toBeInstanceOf(NotFound);
    await expect(editJob("job_1", undefined, form({}))).rejects.toBeInstanceOf(NotFound);
    await expect(confirmJob("job_1")).rejects.toBeInstanceOf(NotFound);
    expect(sent).toEqual([]);
  });
});

describe("applicants", () => {
  let asha: string;
  let appId: string;
  beforeEach(async () => {
    await aJob(true);
    asha = await candidate("asha@example.com", "subject:aaaa");
    await as(asha);
    await applyToJob("job_1");
    await applyToJob("job_1");
    appId = (await db.application.findFirstOrThrow()).id;
    await as(ravi.id);
  });

  it("applying twice is one application, and a closed job takes none", async () => {
    expect(await db.application.count()).toBe(1);
    await db.job.update({ where: { id: "job_1" }, data: { open: false } });
    const bo = await candidate("bo@example.com", "subject:bbbb", "Bo");
    await as(bo);
    expect((await applyToJob("job_1"))?.message).toMatch(/not open/);
    expect(await db.application.count()).toBe(1);
  });

  it("an assessment is issued for the applicant's subject_ref and this job", async () => {
    modules({ "POST http://assess.test/v1/sessions": [200, { tasks: [{ session_id: "as_9" }], not_assessable: ["python"] }] });
    const state = await sendAssessment("job_1", appId, undefined, form({ startBy: dayIn(7) }));
    expect(sent[0].body).toEqual({
      candidate_ref: "subject:aaaa", job_id: "job_1", model: false, start_by: endOfDay(dayIn(7)).toISOString(),
    });
    expect(state?.message).toMatch(/Not assessable.*python/);
    expect(await db.assessment.findUniqueOrThrow({ where: { id: "as_9" } })).toMatchObject({ applicationId: appId, candidateId: asha });
    expect((await db.application.findUniqueOrThrow({ where: { id: appId } })).status).toBe("ASSESSMENT_SENT");
  });

  it("sending twice keeps one row per task: assessment returns the same sessions", async () => {
    const issued = { tasks: [{ session_id: "as_9" }, { session_id: "as_10" }], not_assessable: [] };
    modules({ "POST http://assess.test/v1/sessions": [200, issued] });
    await sendAssessment("job_1", appId, undefined, form({ startBy: dayIn(7) }));
    await sendAssessment("job_1", appId, undefined, form({ startBy: dayIn(7) }));
    expect((await db.assessment.findMany({ orderBy: { id: "asc" } })).map((a) => a.id)).toEqual(["as_10", "as_9"]);
  });

  it("a start-by date that has passed, or is too far off, is refused before anything is sent", async () => {
    modules({});
    for (const [day, why] of [[dayIn(-1), /already passed/], [dayIn(90), /At most 60 days/], ["", /Pick a date/]] as const) {
      const state = await sendAssessment("job_1", appId, undefined, form({ startBy: day, model: "on" }));
      expect(state?.errors?.startBy?.join(" ")).toMatch(why);
      expect(state?.values).toEqual({ startBy: day, model: "on" }); // the form comes back as typed
    }
    expect(sent).toEqual([]);
  });

  it("the candidate submitting moves the application on", async () => {
    await db.assessment.create({ data: { id: "as_9", candidateId: asha, applicationId: appId } });
    await db.application.update({ where: { id: appId }, data: { status: "ASSESSMENT_SENT" } });
    await as(asha);
    modules({ "POST http://assess.test/v1/sessions/as_9/submit": [200, { outcome: "passed" }] });
    await redirectOf(submitSolution("as_9", undefined, form({ code: "x = 1" })));
    expect((await db.application.findUniqueOrThrow({ where: { id: appId } })).status).toBe("SUBMITTED");
  });

  it("a decision needs an outcome and a reason, is made once, and says who made it", async () => {
    const refused = await decide("job_1", appId, undefined, form({ outcome: "REJECT", reason: "no" }));
    expect(refused?.errors?.reason).toBeDefined();
    expect(refused?.values).toEqual({ outcome: "REJECT", reason: "no" }); // the choice is not lost
    await decide("job_1", appId, undefined, form({ outcome: "ADVANCE", reason: "Passed every rate-limiting test." }));
    expect((await decide("job_1", appId, undefined, form({ outcome: "REJECT", reason: "Changed my mind entirely." })))?.message)
      .toMatch(/Already decided/);
    const d = await db.decision.findUniqueOrThrow({ where: { applicationId: appId } });
    expect(d).toMatchObject({ outcome: "ADVANCE", decidedById: ravi.id, reason: "Passed every rate-limiting test." });
    expect((await db.application.findUniqueOrThrow({ where: { id: appId } })).status).toBe("DECIDED");
  });

  it("another organisation's recruiter cannot reach the applicant at all", async () => {
    const other = await recruiter("x@other.example", "Other");
    await as(other.id);
    modules({});
    await expect(myApplication([other.orgId], "job_1", appId)).rejects.toBeInstanceOf(NotFound);
    await expect(decide("job_1", appId, undefined, form({ outcome: "HIRE", reason: "I am not their recruiter." })))
      .rejects.toBeInstanceOf(NotFound);
    expect(await db.decision.count()).toBe(0);
  });
});
