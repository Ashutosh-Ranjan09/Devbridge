/** The candidate's actions and the hand-off to M6, with the modules faked at fetch. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { form, jar, NotFound, redirectOf, resetDb } from "./next";

const { beginTask, finishTask, runExamples, startPractice, submitSolution, uploadCv } = await import("@/app/candidate/actions");
const { myVerification } = await import("@/lib/candidate");
const { db } = await import("@/lib/db");
const { createSession } = await import("@/lib/session");
const { forwardPending, forwardReport } = await import("@/lib/sync");

type Sent = { url: string; method: string; body: unknown };
let sent: Sent[] = [];

/** Fake modules: `routes` maps "METHOD url-prefix" to [status, body]. */
function modules(routes: Record<string, [number, unknown]>) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    sent.push({ url, method, body: init.body });
    const hit = Object.entries(routes).find(([k]) => {
      const [m, prefix] = k.split(" ");
      return m === method && url.startsWith(prefix);
    });
    if (!hit) throw new TypeError(`fetch failed: ${method} ${url}`);
    const [status, body] = hit[1];
    return new Response(JSON.stringify(body), { status });
  }));
}

const PDF = (name = "cv.pdf", bytes = 2048) => new File([new Uint8Array(bytes)], name, { type: "application/pdf" });

async function candidate(email: string, subjectRef: string) {
  const user = await db.user.create({
    data: { email, name: "Asha Rao", passwordHash: "x", role: "CANDIDATE", candidate: { create: { subjectRef } } },
  });
  return user.id;
}

let asha: string;
beforeEach(async () => {
  jar.clear();
  sent = [];
  await resetDb();
  asha = await candidate("asha@example.com", "subject:aaaa");
  await createSession(asha);
});
afterEach(() => vi.unstubAllGlobals());

describe("uploading a CV", () => {
  it("sends the file with the subject_ref, and nothing that names the person", async () => {
    modules({ "POST http://m5.test/v1/verifications": [202, { verification_id: "vr_1", status: "queued" }] });
    const f = new FormData();
    f.set("cv", PDF());
    expect(await redirectOf(uploadCv(undefined, f))).toBe("/candidate/cv/vr_1");
    const body = sent[0].body as FormData;
    expect(JSON.parse(String(body.get("subject")))).toEqual({ subject_ref: "subject:aaaa" });
    expect((body.get("document") as File).name).toBe("cv.pdf");
    const fields = [...body.entries()].filter(([, v]) => typeof v === "string").map(([, v]) => v).join(" ");
    expect(fields).not.toMatch(/asha|Asha Rao/i);
    expect(await db.verification.findUniqueOrThrow({ where: { id: "vr_1" } })).toMatchObject({ candidateId: asha, fileName: "cv.pdf" });
  });

  it("refuses a wrong file before sending it anywhere", async () => {
    modules({});
    for (const file of [PDF("cv.png"), PDF("cv.pdf", 0), PDF("cv.pdf", 6 * 1024 * 1024)]) {
      const f = new FormData();
      f.set("cv", file);
      expect((await uploadCv(undefined, f))?.errors?.cv).toBeDefined();
    }
    expect(sent).toEqual([]);
  });

  it("M5 not answering is said, and nothing is recorded", async () => {
    modules({});
    const f = new FormData();
    f.set("cv", PDF());
    expect((await uploadCv(undefined, f))?.message).toMatch(/not answering/);
    expect(await db.verification.count()).toBe(0);
  });

  it("typed usernames go to M5 and are kept for next time; empty boxes send nothing", async () => {
    modules({ "POST http://m5.test/v1/verifications": [202, { verification_id: "vr_1", status: "queued" }] });
    const f = new FormData();
    f.set("cv", PDF());
    f.set("leetcode", " asha_r ");
    f.set("github", "");
    await redirectOf(uploadCv(undefined, f));
    expect(JSON.parse(String((sent[0].body as FormData).get("handles")))).toEqual({ leetcode: "asha_r" });
    expect(await db.candidate.findUniqueOrThrow({ where: { userId: asha } })).toMatchObject({
      leetcodeHandle: "asha_r", githubHandle: null, codeforcesHandle: null, codechefHandle: null,
    });

    modules({ "POST http://m5.test/v1/verifications": [202, { verification_id: "vr_2", status: "queued" }] });
    const g = new FormData();
    g.set("cv", PDF());
    await redirectOf(uploadCv(undefined, g));
    expect((sent[1].body as FormData).has("handles")).toBe(false);
    expect((await db.candidate.findUniqueOrThrow({ where: { userId: asha } })).leetcodeHandle).toBeNull(); // emptied, so cleared
  });

  it("a note stays here, beside the report, and never reaches M5", async () => {
    modules({ "POST http://m5.test/v1/verifications": [202, { verification_id: "vr_1", status: "queued" }] });
    const f = new FormData();
    f.set("cv", PDF());
    f.set("note", "  I also mentor juniors at the coding club.  ");
    await redirectOf(uploadCv(undefined, f));
    const sentFields = [...(sent[0].body as FormData).entries()].filter(([, v]) => typeof v === "string").map(([, v]) => v).join(" ");
    expect(sentFields).not.toMatch(/mentor/);
    expect((await db.verification.findUniqueOrThrow({ where: { id: "vr_1" } })).note).toBe("I also mentor juniors at the coding club.");
  });

  it("an over-long note is refused before anything is sent, and comes back as typed", async () => {
    modules({});
    const f = new FormData();
    f.set("cv", PDF());
    f.set("note", "x".repeat(2001));
    const state = await uploadCv(undefined, f);
    expect(state?.errors?.note).toEqual(["At most 2,000 characters."]);
    expect(state?.values?.note).toHaveLength(2001);
    expect(sent).toEqual([]);
  });

  it("a link instead of a username is refused before anything is sent, and what was typed comes back", async () => {
    modules({});
    const f = new FormData();
    f.set("cv", PDF());
    f.set("codeforces", "https://codeforces.com/profile/asha");
    const state = await uploadCv(undefined, f);
    expect(state?.errors?.codeforces).toBeDefined();
    expect(state?.values?.codeforces).toBe("https://codeforces.com/profile/asha");
    expect(sent).toEqual([]);
  });

  it("another candidate's report is a 404, the same as one that does not exist", async () => {
    const ravi = await candidate("ravi@example.com", "subject:bbbb");
    await db.verification.create({ data: { id: "vr_ravi", candidateId: ravi, fileName: "r.pdf" } });
    await expect(myVerification(asha, "vr_ravi")).rejects.toBeInstanceOf(NotFound);
    await expect(myVerification(asha, "vr_none")).rejects.toBeInstanceOf(NotFound);
  });
});

describe("assessments", () => {
  const TASK = { tasks: [{ session_id: "as_1", title: "Rate limiter" }], not_assessable: [] };

  it("practice is issued for the subject_ref, and starting again opens the same task", async () => {
    modules({ "POST http://assess.test/v1/sessions": [200, TASK] });
    expect(await redirectOf(startPractice("rate_limiter"))).toBe("/candidate/assessments/as_1");
    expect(await redirectOf(startPractice("rate_limiter"))).toBe("/candidate/assessments/as_1");
    expect(JSON.parse(String(sent[0].body))).toEqual({ candidate_ref: "subject:aaaa", pattern_id: "rate_limiter" });
    expect(await db.assessment.count()).toBe(1);
  });

  it("a scored submission goes to M6, unchanged", async () => {
    await db.assessment.create({ data: { id: "as_1", candidateId: asha } });
    const batch = { batch_id: "evb_1", subject_ref: "subject:aaaa", events: [] };
    modules({
      "POST http://assess.test/v1/sessions/as_1/submit": [200, { outcome: "passed", final: true }],
      "GET http://assess.test/v1/sessions/as_1/events": [200, batch],
      "POST http://m6.test/evidence/batch": [202, { accepted: ["ev_1"] }],
    });
    expect(await redirectOf(submitSolution("as_1", undefined, form({ code: "x = 1" })))).toBe("/candidate/assessments/as_1");
    expect(JSON.parse(String(sent[2].body))).toEqual(batch);
    expect((await db.assessment.findUniqueOrThrow({ where: { id: "as_1" } })).sentToM6At).not.toBeNull();
  });

  it("an attempt that is not final stays with the candidate: nothing goes to M6", async () => {
    await db.assessment.create({ data: { id: "as_1", candidateId: asha } });
    modules({ "POST http://assess.test/v1/sessions/as_1/submit": [200, { outcome: "tests_failed", attempt: 1, final: false, attempts_left: 2 }] });
    expect(await redirectOf(submitSolution("as_1", undefined, form({ code: "x = 1" })))).toBe("/candidate/assessments/as_1");
    expect(sent.map((s) => s.url)).toEqual(["http://assess.test/v1/sessions/as_1/submit"]);
    expect((await db.assessment.findUniqueOrThrow({ where: { id: "as_1" } })).sentToM6At).toBeNull();
  });

  it("finishing makes the last attempt count and sends it to M6", async () => {
    await db.assessment.create({ data: { id: "as_1", candidateId: asha } });
    modules({
      "POST http://assess.test/v1/sessions/as_1/finish": [200, { outcome: "tests_failed", attempt: 2 }],
      "GET http://assess.test/v1/sessions/as_1/events": [200, { batch_id: "evb_1" }],
      "POST http://m6.test/evidence/batch": [202, { accepted: ["ev_1"] }],
    });
    expect(await redirectOf(finishTask("as_1"))).toBe("/candidate/assessments/as_1");
    expect((await db.assessment.findUniqueOrThrow({ where: { id: "as_1" } })).sentToM6At).not.toBeNull();
  });

  it("Run returns the examples to the form with the code, and stores nothing", async () => {
    await db.assessment.create({ data: { id: "as_1", candidateId: asha } });
    const examples = { outcome: "tests_failed", note: null,
      examples: [{ name: "example_over_the_limit", passed: false, detail: "got 200, expected 429" }] };
    modules({ "POST http://assess.test/v1/sessions/as_1/run": [200, examples] });
    const state = await runExamples("as_1", undefined, form({ code: "x = 1" }));
    expect(state).toEqual({ examples, values: { code: "x = 1" } });
    expect((await db.assessment.findUniqueOrThrow({ where: { id: "as_1" } })).sentToM6At).toBeNull();
  });

  it("code that does not parse is said with its line, and the code comes back", async () => {
    await db.assessment.create({ data: { id: "as_1", candidateId: asha } });
    const refusal = { error: "syntax_error", detail: "line 37: unterminated string literal. Not submitted; no attempt used" };
    modules({
      "POST http://assess.test/v1/sessions/as_1/submit": [422, refusal],
      "POST http://assess.test/v1/sessions/as_1/run": [422, refusal],
    });
    const submitted = await submitSolution("as_1", undefined, form({ code: 'x = "wind' }));
    expect(submitted?.message).toMatch(/line 37.*no attempt used/);
    expect(submitted?.values?.code).toBe('x = "wind');
    expect((await runExamples("as_1", undefined, form({ code: 'x = "wind' })))?.message).toMatch(/line 37/);
  });

  it("nobody runs code on another candidate's task", async () => {
    const ravi = await candidate("ravi@example.com", "subject:bbbb");
    await db.assessment.create({ data: { id: "as_ravi", candidateId: ravi } });
    modules({});
    await expect(runExamples("as_ravi", undefined, form({ code: "x" }))).rejects.toBeInstanceOf(NotFound);
    await expect(finishTask("as_ravi")).rejects.toBeInstanceOf(NotFound);
    expect(sent).toEqual([]);
  });

  it("an unrunnable sandbox is said, and nothing goes to M6", async () => {
    await db.assessment.create({ data: { id: "as_1", candidateId: asha } });
    modules({
      "POST http://assess.test/v1/sessions/as_1/submit": [503, { error: "sandbox_unavailable", detail: "No such image — nothing was measured; the session is still open" }],
    });
    const state = await submitSolution("as_1", undefined, form({ code: "x = 1" }));
    expect(state?.message).toMatch(/still open/);
    expect(state?.values?.code).toBe("x = 1"); // the editor shows the candidate's code again, not the starter
    expect(sent.map((s) => s.url)).toEqual(["http://assess.test/v1/sessions/as_1/submit"]);
  });

  it("M6 being down does not lose the submission; it stays pending", async () => {
    await db.assessment.create({ data: { id: "as_1", candidateId: asha } });
    modules({
      "POST http://assess.test/v1/sessions/as_1/submit": [200, { outcome: "passed", final: true }],
      "GET http://assess.test/v1/sessions/as_1/events": [200, { batch_id: "evb_1" }],
    });
    expect(await redirectOf(submitSolution("as_1", undefined, form({ code: "x = 1" })))).toBe("/candidate/assessments/as_1");
    expect((await db.assessment.findUniqueOrThrow({ where: { id: "as_1" } })).sentToM6At).toBeNull();
  });

  it("Start begins the candidate's own task, and a passed start-by date is said", async () => {
    await db.assessment.create({ data: { id: "as_1", candidateId: asha } });
    modules({ "POST http://assess.test/v1/sessions/as_1/begin": [200, { session_id: "as_1", status: "open" }] });
    expect(await redirectOf(beginTask("as_1"))).toBe("/candidate/assessments/as_1");
    expect(sent.map((s) => `${s.method} ${s.url}`)).toEqual(["POST http://assess.test/v1/sessions/as_1/begin"]);
    modules({ "POST http://assess.test/v1/sessions/as_1/begin": [409, { error: "refused", detail: "the start-by date passed" }] });
    expect((await beginTask("as_1"))?.message).toMatch(/start-by date passed/);
  });

  it("nobody starts another candidate's task", async () => {
    const ravi = await candidate("ravi@example.com", "subject:bbbb");
    await db.assessment.create({ data: { id: "as_ravi", candidateId: ravi } });
    modules({});
    await expect(beginTask("as_ravi")).rejects.toBeInstanceOf(NotFound);
    expect(sent).toEqual([]);
  });

  it("nobody submits to another candidate's session", async () => {
    const ravi = await candidate("ravi@example.com", "subject:bbbb");
    await db.assessment.create({ data: { id: "as_ravi", candidateId: ravi } });
    modules({});
    await expect(submitSolution("as_ravi", undefined, form({ code: "x" }))).rejects.toBeInstanceOf(NotFound);
    expect(sent).toEqual([]);
  });
});

describe("forwarding to M6", () => {
  const report = (status: string) => ({ verification_id: "vr_1", status }) as never;

  it("a failed report is not sent: nothing was verified", async () => {
    await db.verification.create({ data: { id: "vr_1", candidateId: asha, fileName: "cv.pdf" } });
    modules({});
    await forwardReport("vr_1", report("failed"));
    expect(sent).toEqual([]);
  });

  it("pending items are sent once M5 has finished, and a running one waits", async () => {
    await db.verification.create({ data: { id: "vr_done", candidateId: asha, fileName: "a.pdf" } });
    await db.verification.create({ data: { id: "vr_running", candidateId: asha, fileName: "b.pdf" } });
    modules({
      "GET http://m5.test/v1/verifications/vr_done": [200, report("completed")],
      "GET http://m5.test/v1/verifications/vr_running": [202, { status: "running" }],
      "POST http://m6.test/evidence/report": [202, { accepted: [] }],
    });
    await forwardPending(asha);
    const sentToM6 = await db.verification.findMany({ where: { sentToM6At: { not: null } } });
    expect(sentToM6.map((v) => v.id)).toEqual(["vr_done"]);
    expect(sent.filter((s) => s.url.startsWith("http://m6.test")).length).toBe(1);
  });
});
