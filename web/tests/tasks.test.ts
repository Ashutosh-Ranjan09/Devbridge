/** A job's results as the recruiter reads them: only this job's applicants, and why a
 * task has no result yet. The ranking itself is the assessment module's. */

import { describe, expect, it } from "vitest";

const { forApplicants, pendingStatus } = await import("@/lib/tasks");

describe("a job's results", () => {
  it("shows only sessions issued to this job's applicants, with who each is, in the module's order", () => {
    const ranked = [
      { rank: 1, session_id: "as_b" },
      { rank: 2, session_id: "as_elsewhere" }, // not issued by this site for this job
      { rank: 3, session_id: "as_a" },
    ];
    const who = new Map([["as_a", { name: "Asha" }], ["as_b", { name: "Bo" }]]);
    expect(forApplicants(ranked, who).map((r) => [r.rank, r.who.name])).toEqual([[1, "Bo"], [3, "Asha"]]);
  });

  it("says why a task has no result yet", () => {
    const p = { session_id: "as_1", candidate_ref: "s", attempts_used: 0, start_by: null, started: false };
    expect(pendingStatus({ ...p, status: "open", attempts_used: 1 }, 3)).toBe("open · 1 of 3 attempts used");
    expect(pendingStatus({ ...p, status: "issued" }, 3)).toBe("not started");
    expect(pendingStatus({ ...p, status: "issued", start_by: "2026-11-03T18:29:59Z" }, 3)).toMatch(/^not started · start by 3 Nov 2026/);
    expect(pendingStatus({ ...p, status: "expired" }, 3)).toBe("expired · never started");
    expect(pendingStatus({ ...p, status: "expired", started: true }, 3)).toBe("expired · nothing submitted in time");
  });
});
