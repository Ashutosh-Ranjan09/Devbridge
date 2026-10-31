/** M6's job match in words. The range travels with the middle, and the line says how many
 * of the job's skills it rests on, so a match made mostly of "nothing known" reads as one. */

import type { JobMatch, Shortlist } from "./types";

const two = (n: number) => n.toFixed(2);

export function matchText(m: JobMatch): string {
  return `${two(m.mean)} (${two(m.interval[0])}–${two(m.interval[1])}) · evidence for ${m.evidence_for} of ${m.of} skill${m.of === 1 ? "" : "s"}`;
}

/** How M6 made every match on the page, in one sentence. */
export function basisText({ weights, without_evidence: none }: Shortlist["job_match_basis"]): string {
  return `In a job match a must-have counts ${weights.must} and a nice-to-have ${weights.nice}; `
    + `a skill with no evidence counts ${two(none.mean)} (${two(none.interval[0])}–${two(none.interval[1])}).`;
}
