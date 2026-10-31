import "server-only";

import { call, ServiceError } from "./services";
import type { Report, Rule } from "./types";

/** M5's live catalogue of checks, or null when M5 does not answer: a report page then
 * shows the report without the extra lines rather than failing. */
export async function m5Rules(): Promise<Rule[] | null> {
  try {
    return await call<Rule[]>("m5", "/v1/rules");
  } catch (e) {
    if (e instanceof ServiceError) return null;
    throw e;
  }
}

/** What `cvv verify` prints as "also checked, nothing raised" (cvv.report.quietly_clean):
 * a check below decisive that ran and found nothing. A decisive one that came back clean
 * is already a line under Verified, and one with a note is printed there in full, so
 * both are left out — the same rule as M5's own CLI, read off the report's outcomes. */
export function alsoChecked(report: Report, rules: Rule[] | null): string[] {
  if (!rules) return [];
  const byId = new Map(rules.map((r) => [r.rule_id, r]));
  return report.findings.rule_outcomes
    .filter((o) => o.status === "clean" && !o.note && byId.get(o.rule_id)?.tier !== "decisive")
    .flatMap((o) => {
      const rule = byId.get(o.rule_id);
      return rule ? [rule.summary] : [];
    });
}
