/** The CLI's "also checked, nothing raised" lines, read off a report's outcomes. */

import { describe, expect, it } from "vitest";

const { alsoChecked } = await import("@/lib/m5");
import type { Report, Rule } from "@/lib/types";

const RULES: Rule[] = [
  { rule_id: "P1", version: "1.0", tier: "decisive", scoring: true, summary: "Claimed Codeforces rating vs. the API" },
  { rule_id: "G8", version: "1.0", tier: "attention", scoring: true, summary: "Portfolio composition" },
  { rule_id: "G10", version: "1.0", tier: "evidence_only", scoring: false, summary: "Public commits during a role" },
  { rule_id: "D11", version: "1.0", tier: "attention", scoring: false, summary: "Gaps between dated roles" },
];

const report = (outcomes: Report["findings"]["rule_outcomes"]) =>
  ({ findings: { rule_outcomes: outcomes } }) as unknown as Report;

describe("also checked, nothing raised", () => {
  it("is a check below decisive that ran clean, as cvv.report.quietly_clean", () => {
    const lines = alsoChecked(report([
      { rule_id: "P1", status: "clean" }, // decisive: already a line under Verified
      { rule_id: "G8", status: "clean" },
      { rule_id: "G10", status: "clean", note: "commits during the role" }, // printed under Verified
      { rule_id: "D11", status: "fired" },
    ]), RULES);
    expect(lines).toEqual(["Portfolio composition"]);
  });

  it("says nothing when M5's catalogue could not be read", () => {
    expect(alsoChecked(report([{ rule_id: "G8", status: "clean" }]), null)).toEqual([]);
  });

  it("leaves out an outcome for a rule the catalogue does not list", () => {
    expect(alsoChecked(report([{ rule_id: "Z9", status: "clean" }]), RULES)).toEqual([]);
  });
});
