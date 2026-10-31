/** Chat: only a recruiter opens a thread, only the people on it reach it, and only user
 * ids reach the chat module. The module is faked at fetch. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { form, jar, NotFound, redirectOf, resetDb } from "./next";

const { startChat } = await import("@/app/recruiter/actions");
const { markRead, requestDocument, sendFile, sendMessage } = await import("@/app/chat/actions");
const { GET } = await import("@/app/api/chat/[appId]/stream/route");
const { GET: download } = await import("@/app/api/chat/[appId]/files/[fileId]/route");
const { MAX_FILE_BYTES } = await import("@/lib/definitions");
const { db } = await import("@/lib/db");
const { createSession } = await import("@/lib/session");

type Sent = { url: string; method: string; body: unknown; headers: Record<string, string> };
let sent: Sent[] = [];

function chat(routes: Record<string, () => Response>) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    sent.push({ url, method, body: typeof init.body === "string" ? JSON.parse(init.body) : init.body,
                headers: (init.headers ?? {}) as Record<string, string> });
    const hit = Object.entries(routes).find(([k]) => {
      const [m, prefix] = k.split(" ");
      return m === method && url.startsWith(prefix);
    });
    if (!hit) throw new TypeError(`fetch failed: ${method} ${url}`);
    return hit[1]();
  }));
}
const json = (status: number, body: unknown) => () => new Response(JSON.stringify(body), { status });

const as = async (userId: string) => {
  jar.clear();
  await createSession(userId);
};

let ravi: string, meera: string, asha: string, bo: string, admin: string, other: string;
let orgId: string, appId: string;

beforeEach(async () => {
  sent = [];
  await resetDb();
  const org = await db.organisation.create({ data: { name: "PayFlow", kind: "ENTERPRISE" } });
  orgId = org.id;
  const recruiter = async (email: string, name: string, org = orgId) => (await db.user.create({
    data: { email, name, passwordHash: "x", role: "RECRUITER", memberships: { create: { orgId: org } } },
  })).id;
  const candidate = async (email: string, name: string, ref: string) => (await db.user.create({
    data: { email, name, passwordHash: "x", role: "CANDIDATE", candidate: { create: { subjectRef: ref } } },
  })).id;
  ravi = await recruiter("ravi@payflow.example", "Ravi");
  meera = await recruiter("meera@payflow.example", "Meera");
  const elsewhere = await db.organisation.create({ data: { name: "Other", kind: "ENTERPRISE" } });
  other = await recruiter("x@other.example", "Xavier", elsewhere.id);
  asha = await candidate("asha@example.com", "Asha Rao", "subject:aaaa");
  bo = await candidate("bo@example.com", "Bo", "subject:bbbb");
  admin = (await db.user.create({ data: { email: "admin@example.com", name: "Admin", passwordHash: "x", role: "ADMIN" } })).id;
  await db.job.create({ data: { id: "job_1", title: "Backend", orgId, createdById: ravi, open: true } });
  appId = (await db.application.create({ data: { jobId: "job_1", candidateId: asha } })).id;
});
afterEach(() => vi.unstubAllGlobals());

describe("opening a chat", () => {
  it("is the recruiter's, and sends ids only — never a name or an email", async () => {
    await as(ravi);
    chat({ "POST http://chat.test/v1/threads": json(200, {}) });
    expect(await redirectOf(startChat("job_1", appId))).toBe(`/recruiter/messages/${appId}`);
    expect(sent[0].body).toEqual({ thread_id: appId, candidate: asha, org: orgId, started_by: ravi });
    expect(sent[0].headers.Authorization).toBe("Bearer chat-key");
    expect(JSON.stringify(sent[0].body)).not.toMatch(/Asha|Ravi|@/);
  });

  it("another company's recruiter cannot, and nothing is sent", async () => {
    await as(other);
    chat({});
    await expect(startChat("job_1", appId)).rejects.toBeInstanceOf(NotFound);
    expect(sent).toEqual([]);
  });
});

describe("sending", () => {
  it("a candidate writing before any recruiter has opened the chat is told so", async () => {
    await as(asha);
    chat({ [`POST http://chat.test/v1/threads/${appId}/messages`]: json(404, { error: "no_thread", detail: "x" }) });
    const state = await sendMessage(appId, undefined, form({ body: "Hello, any update?" }));
    expect(state?.message).toMatch(/not started a chat/);
    expect(state?.values).toEqual({ body: "Hello, any update?" }); // not lost
  });

  it("goes as the sender's id and side; any recruiter of the company may write", async () => {
    chat({ [`POST http://chat.test/v1/threads/${appId}/messages`]: json(201, {}) });
    await as(asha);
    expect(await sendMessage(appId, undefined, form({ body: "  Thanks!  " }))).toBeUndefined();
    await as(meera);
    await sendMessage(appId, undefined, form({ body: "Friday works.\r\nBring your ID." }));
    expect(sent.map((s) => s.body)).toEqual([
      { sender: asha, side: "candidate", body: "Thanks!" },
      { sender: meera, side: "recruiter", body: "Friday works.\nBring your ID." },
    ]);
  });

  it("an empty message is refused before anything is sent", async () => {
    await as(asha);
    chat({});
    const state = await sendMessage(appId, undefined, form({ body: "   " }));
    expect(state?.errors?.body).toBeDefined();
    expect(sent).toEqual([]);
  });

  it("someone not on the thread gets a 404: another candidate, another company, an admin", async () => {
    chat({});
    for (const who of [bo, other, admin]) {
      await as(who);
      await expect(sendMessage(appId, undefined, form({ body: "hi" }))).rejects.toBeInstanceOf(NotFound);
      await expect(markRead(appId, 1)).rejects.toBeInstanceOf(NotFound);
    }
    expect(sent).toEqual([]);
  });

  it("a read mark goes as the reader's id and side; a nonsense one is not sent", async () => {
    await as(meera);
    chat({ [`POST http://chat.test/v1/threads/${appId}/read`]: json(200, {}) });
    await markRead(appId, 7);
    await markRead(appId, -1);
    expect(sent.map((s) => s.body)).toEqual([{ reader: meera, side: "recruiter", seq: 7 }]);
  });
});

describe("the live stream", () => {
  const request = (headers: Record<string, string> = {}) =>
    GET(new Request(`http://web.test/api/chat/${appId}/stream?after=3`, { headers }),
        { params: Promise.resolve({ appId }) });

  it("is relayed for the people on the thread, resuming where the browser left off", async () => {
    await as(asha);
    chat({ [`GET http://chat.test/v1/threads/${appId}/events`]: () =>
      new Response("id: 5\nevent: message\ndata: {}\n\n", { headers: { "Content-Type": "text/event-stream" } }) });
    const response = await request({ "Last-Event-ID": "4" });
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/event-stream");
    expect(await response.text()).toBe("id: 5\nevent: message\ndata: {}\n\n");
    expect(sent[0].url).toBe(`http://chat.test/v1/threads/${appId}/events?after=4`);
    await request({ "Last-Event-ID": "4; DROP" });
    expect(sent[1].url).toMatch(/after=0$/);
  });

  it("is a 404 for anyone else, admins included, before the chat module is asked", async () => {
    chat({});
    for (const who of [bo, other, admin]) {
      await as(who);
      expect((await request()).status).toBe(404);
    }
    jar.clear();
    expect((await request()).status).toBe(404);
    expect(sent).toEqual([]);
  });

  it("a thread nobody opened ends the stream rather than retrying forever", async () => {
    await as(asha);
    chat({ [`GET http://chat.test/v1/threads/${appId}/events`]: json(404, { error: "no_thread", detail: "x" }) });
    expect((await request()).status).toBe(204);
  });
});

describe("documents and files", () => {
  const pdf = () => new File([new TextEncoder().encode("%PDF-1.7 the degree")], "degree.pdf", { type: "application/pdf" });
  const files = (f: FormData | undefined) => Object.fromEntries([...(f ?? new FormData()).entries()].map(([k, v]) => [k, typeof v === "string" ? v : `file:${v.name}`]));

  it("only a recruiter asks for a document; to a candidate the action does not exist", async () => {
    chat({ [`POST http://chat.test/v1/threads/${appId}/messages`]: json(201, {}) });
    await as(asha);
    await expect(requestDocument(appId, undefined, form({ what: "Your manager's number" }))).rejects.toBeInstanceOf(NotFound);
    await as(ravi);
    expect((await requestDocument(appId, undefined, form({ what: "  " })))?.errors?.what).toBeDefined();
    await requestDocument(appId, undefined, form({ what: "Degree certificate" }));
    expect(sent.map((x) => x.body)).toEqual([{ sender: ravi, side: "recruiter", kind: "request", body: "Degree certificate" }]);
  });

  it("a file goes as the sender's id and side, with the request it answers", async () => {
    await as(asha);
    chat({ [`POST http://chat.test/v1/threads/${appId}/files`]: json(201, {}) });
    const f = new FormData();
    f.set("file", pdf());
    f.set("note", " scanned today ");
    f.set("request", "msg_0123456789abcdef");
    expect(await sendFile(appId, undefined, f)).toBeUndefined();
    expect(files(sent[0].body as FormData)).toEqual({
      sender: asha, side: "candidate", note: "scanned today", request_id: "msg_0123456789abcdef", file: "file:degree.pdf",
    });
  });

  it("an empty, oversized or misaddressed file is refused before anything is sent", async () => {
    await as(asha);
    chat({});
    for (const [file, request] of [
      [new File([], "empty.pdf"), ""],
      [new File([new Uint8Array(MAX_FILE_BYTES + 1)], "big.pdf"), ""],
      [pdf(), "../../files/x"],
    ] as const) {
      const f = new FormData();
      f.set("file", file);
      f.set("request", request);
      const state = await sendFile(appId, undefined, f);
      expect(state?.errors).toBeDefined();
    }
    expect(sent).toEqual([]);
  });

  it("the chat module's refusal of a type is shown as it said it", async () => {
    await as(asha);
    chat({ [`POST http://chat.test/v1/threads/${appId}/files`]: json(415, { error: "unsupported_file", detail: "Send a PDF, PNG, JPG or DOCX file." }) });
    const f = new FormData();
    f.set("file", new File(["<html>"], "cv.pdf"));
    expect((await sendFile(appId, undefined, f))?.message).toBe("Send a PDF, PNG, JPG or DOCX file.");
  });

  const get = (fileId: string) =>
    download(new Request(`http://web.test/api/chat/${appId}/files/${fileId}`), { params: Promise.resolve({ appId, fileId }) });

  it("a download is always an attachment, of the sniffed type, with nothing allowed to run", async () => {
    await as(meera);
    chat({ [`GET http://chat.test/v1/threads/${appId}/files/file_0123456789abcdef`]: () =>
      new Response("%PDF-1.7", { headers: { "Content-Type": "application/pdf", "X-File-Name": encodeURIComponent("Asha’s degree.pdf") } }) });
    const r = await get("file_0123456789abcdef");
    expect(r.status).toBe(200);
    expect(await r.text()).toBe("%PDF-1.7");
    expect(r.headers.get("Content-Type")).toBe("application/pdf");
    expect(r.headers.get("Content-Disposition")).toBe(`attachment; filename*=UTF-8''${encodeURIComponent("Asha’s degree.pdf")}`);
    expect(r.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(r.headers.get("Content-Security-Policy")).toMatch(/sandbox/);
    expect(r.headers.get("Cache-Control")).toMatch(/no-store/);
  });

  it("a download is a 404 for anyone not on the thread, and for an id that is not a file's", async () => {
    chat({});
    for (const who of [bo, other, admin]) {
      await as(who);
      expect((await get("file_0123456789abcdef")).status).toBe(404);
    }
    await as(asha);
    expect((await get("../../etc/passwd")).status).toBe(404);
    expect(sent).toEqual([]);
  });
});
