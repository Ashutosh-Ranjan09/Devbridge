/** Calling the modules: one error shape out of three, and an honest "not answering". */

import { afterEach, describe, expect, it, vi } from "vitest";

const { call, errorOf, health, ServiceError } = await import("@/lib/services");

afterEach(() => vi.unstubAllGlobals());

/** The ServiceError a call rejects with. */
async function failure(run: Promise<unknown>): Promise<InstanceType<typeof ServiceError>> {
  const e = await run.then(() => null, (x: unknown) => x);
  if (!(e instanceof ServiceError)) throw new Error(`expected a ServiceError, got ${String(e)}`);
  return e;
}

const answer = (status: number, body: unknown) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status }));

describe("errorOf", () => {
  it("reads M6's and assessment's flat shape", () => {
    expect(errorOf({ error: "refused", detail: "a confirmed job is never edited" }, 409))
      .toEqual({ code: "refused", message: "a confirmed job is never edited" });
  });

  it("reads M5's nested shape, and its plain string", () => {
    expect(errorOf({ detail: { error: "no_document", detail: "Supply a file" } }, 422))
      .toEqual({ code: "no_document", message: "Supply a file" });
    expect(errorOf({ detail: "No such verification." }, 404))
      .toEqual({ code: "http_404", message: "No such verification." });
  });

  it("survives a body that is not JSON", () => {
    expect(errorOf(null, 502)).toEqual({ code: "http_502", message: "HTTP 502" });
  });
});

describe("call", () => {
  it("sends the module's key, and only to that module", async () => {
    const fetch = answer(200, []);
    vi.stubGlobal("fetch", fetch);
    await call("assess", "/v1/patterns");
    await call("m6", "/health");
    const headers = fetch.mock.calls.map((c) => (c as unknown[])[1] as RequestInit).map((i) => i.headers);
    expect(headers[0]).toEqual({ Authorization: "Bearer test-key" });
    expect(headers[1]).toEqual({});
  });

  it("a refusal becomes a ServiceError with the module's own reason", async () => {
    vi.stubGlobal("fetch", answer(409, { error: "refused", detail: "a session takes one submission" }));
    const e = await failure(call("assess", "/v1/sessions/x/submit", { body: { code: "" } }));
    expect([e.status, e.code, e.message]).toEqual([409, "refused", "a session takes one submission"]);
  });

  it("no answer at all is status 0, unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    const e = await failure(call("m5", "/healthz"));
    expect([e.status, e.code]).toEqual([0, "unreachable"]);
    expect(e.message).toContain("http://m5.test");
  });
});

describe("health", () => {
  it("an assessment service whose sandbox cannot run is not healthy", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      new Response(JSON.stringify(url.startsWith("http://assess.test")
        ? { status: "degraded", image: "assess-python:3.12", image_present: false }
        : { status: "ok" }), { status: 200 })));
    const byService = Object.fromEntries((await health()).map((h) => [h.service, h]));
    expect(byService.m5.ok && byService.m6.ok).toBe(true);
    expect(byService.assess.ok).toBe(false);
    expect(byService.assess.detail).toContain("not built");
  });
});
