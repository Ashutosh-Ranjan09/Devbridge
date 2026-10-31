/** M6's job match as the recruiter reads it: the range with the middle, and what it rests on.
 * The number itself is M6's. */

import { describe, expect, it } from "vitest";

const { basisText, matchText } = await import("@/lib/match");

describe("a job match", () => {
  it("is shown as a range, with how many of the job's skills have evidence", () => {
    expect(matchText({ interval: [0.327, 0.627], mean: 0.467, evidence_for: 1, of: 2 }))
      .toBe("0.47 (0.33–0.63) · evidence for 1 of 2 skills");
    expect(matchText({ interval: [0.6, 0.8], mean: 0.7, evidence_for: 1, of: 1 })).toMatch(/of 1 skill$/);
  });

  it("says how M6 made it, the value of no evidence included", () => {
    const basis = { weights: { must: 2, nice: 1 }, without_evidence: { interval: [0.083, 0.55] as [number, number], mean: 0.25 } };
    expect(basisText(basis)).toBe("In a job match a must-have counts 2 and a nice-to-have 1; "
      + "a skill with no evidence counts 0.25 (0.08–0.55).");
  });
});
