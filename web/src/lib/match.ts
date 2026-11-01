/** M6's job match in words. The range travels with the middle, and the line says how many
 * of the job's skills it rests on, so a match made mostly of "nothing known" reads as one. */

import type { JobMatch, Shortlist } from "./types";

const two = (n: number) => n.toFixed(2);

export function matchText(m: JobMatch): string {
  return `${two(m.mean)} (${two(m.interval[0])}–${two(m.interval[1])}) · evidence for ${m.evidence_for} of ${m.of} skill${m.of === 1 ? "" : "s"}`;
}

/** A job's applicants by job match, highest middle first. Equal matches, and anyone
 * without one (no evidence on record), follow by name. */
export function byJobMatch<T>(rows: T[], match: (r: T) => JobMatch | null | undefined, name: (r: T) => string): T[] {
  return [...rows].sort((a, b) => (match(b)?.mean ?? -1) - (match(a)?.mean ?? -1) || name(a).localeCompare(name(b)));
}

/** How M6 made every match on the page, in one sentence. */
export function basisText({ weights, without_evidence: none, left_out: out = [] }: Shortlist["job_match_basis"]): string {
  return `In a job match a must-have counts ${weights.must} and a nice-to-have ${weights.nice}; `
    + `a skill with no evidence counts ${two(none.mean)} (${two(none.interval[0])}–${two(none.interval[1])}).`
    + (out.length ? ` Not counted, as the skill list lacks ${out.length === 1 ? "it" : "them"}: ${out.join(", ")}.` : "");
}
