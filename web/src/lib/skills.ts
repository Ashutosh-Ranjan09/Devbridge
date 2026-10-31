import "server-only";

import { call } from "./services";

export type SkillEdge = { from: string; to: string; type: string };

/** The shared skill list through M6's catalogue: each skill's name as people write it
 * ("Next.js"), its tier, and the ontology's edges. M6 down, or a skill it does not list:
 * the id made readable, no tier, no edges. */
export async function skillCatalogue(): Promise<{ label: (id: string) => string; tier: (id: string) => string | null; edges: SkillEdge[] }> {
  const answer = await call<{ skills: { skill_id: string; label?: string; volatility_tier?: string }[]; edges?: SkillEdge[] }>("m6", "/skills")
    .catch(() => ({ skills: [], edges: [] }));
  const labels = new Map(answer.skills.map((r) => [r.skill_id, r.label ?? r.skill_id]));
  const tiers = new Map(answer.skills.map((r) => [r.skill_id, r.volatility_tier ?? null]));
  return {
    label: (id) => labels.get(id) ?? readable(id),
    tier: (id) => tiers.get(id) ?? null,
    edges: answer.edges ?? [],
  };
}

/** Just the names (see skillCatalogue). */
export async function skillLabels(): Promise<(id: string) => string> {
  return (await skillCatalogue()).label;
}

function readable(id: string): string {
  const words = id.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** M6's score (its interval's lower bound, 0–1) out of 100. Shown as it came, only
 * rescaled: the number rises as evidence firms the estimate up. */
export const outOf100 = (score: number): number => Math.round(score * 100);

/** Each kind of evidence M6 counts, said the way a developer would. `against` marks the
 * one kind that pulls a skill down. */
export const EVIDENCE: Record<string, { label: string; detail: string; icon: "Code" | "File" | "Spark" | "Check" | "Building"; against?: true }> = {
  assessment_result: { label: "DevBridge assessment", detail: "A timed coding task you completed here.", icon: "Code" },
  platform_rating: { label: "Competitive programming rating", detail: "Your rating on a contest platform.", icon: "Spark" },
  max_rating: { label: "Peak contest rating", detail: "The highest rating you reached on a contest platform.", icon: "Spark" },
  repo_artifact: { label: "Code on GitHub", detail: "Work in your public repositories.", icon: "Code" },
  claim_corroborated: { label: "CV claim confirmed", detail: "Something your CV says, backed up by your public work.", icon: "Check" },
  artifact_live: { label: "Live project", detail: "A project from your CV that is up and running.", icon: "Building" },
  credential_verified: { label: "Verified credential", detail: "A certificate checked with its issuer.", icon: "Check" },
  cv_claim: { label: "Listed on your CV", detail: "Named on your CV, not yet backed by public work.", icon: "File" },
  claim_contradicted: { label: "CV claim not supported", detail: "Your linked work didn't show what the CV claims.", icon: "File", against: true },
};

export function evidenceOf(kind: string) {
  return EVIDENCE[kind] ?? { label: readable(kind), detail: "", icon: "File" as const };
}
