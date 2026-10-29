/** The parts of each module's answers that pages read — not the whole contract. A field
 * a page does not read is not typed here, so a module adding one changes nothing. */

// ── M5: GET /v1/verifications/{id} ─────────────────────────────────────────

/** 202 while the pipeline runs. */
export type Running = { verification_id: string; status: "running"; created_at: string };

export type Claim = {
  claim_id: string;
  kind: string;
  provenance: { verbatim: string; page?: number | null };
};

export type Discrepancy = {
  finding_id: string;
  rule_id: string;
  tier: "decisive" | "attention" | "evidence_only";
  severity: "info" | "low" | "medium" | "high";
  claim_refs: string[];
  params: Record<string, unknown>;
  explanation: string;
  innocent_explanation: string | null;
};

export type Report = {
  verification_id: string;
  status: "completed" | "completed_degraded" | "failed";
  failure?: string;
  document: { pages: number; ingest_method: "pdf_text" | "docx" | "ocr"; ocr_confidence?: number | null } | null;
  claim_graph: { claims: Claim[] };
  findings: {
    discrepancies: Discrepancy[];
    buckets: {
      verified: string[];
      contradicted: string[];
      needs_context: string[];
      not_evaluated: string[];
      out_of_scope: string[];
    };
  };
  narrative: { summary: string; model_id: string; fallback_used: boolean; rejected_because: string | null } | null;
  coverage: { rules_total: number; rules_evaluated: number; rules_abstained: number; coverage: number };
  valid_as_of: string;
};

/** The params key M5 quotes the CV's own words under (cvv.models.findings.CANDIDATE_TEXT). */
export const CANDIDATE_TEXT = "candidate_text";

// ── M6: GET /developers/{ref}/profile and …/skills/{skill}/explain ─────────

export type Skill = {
  skill_id: string;
  interval: [number, number];
  mean: number;
  volatility_tier: string;
  evidence_count: number;
  inferred: boolean;
  days_since_newest_evidence: number | null;
};

export type Profile = {
  as_of: string;
  skills: Skill[];
  integrity: {
    clean: boolean;
    findings: { check_id: string; severity: string; summary: string; detail: string; innocent_explanation: string | null }[];
    note: string;
  };
  note: string;
};

export type Explanation = {
  skill: string;
  interval: [number, number];
  mean: number;
  evidence_count: number;
  half_life_days: number;
  basis: string;
  contributions: { event_id: string; kind: string; occurred_at: string; observed: number; weight: number; moved_mean_to: number }[];
  not_counted: unknown[];
};

// ── assessment ─────────────────────────────────────────────────────────────

export type Pattern = { id: string; skill: string; title: string; level: string; time_limit_minutes: number; variants: number };

export type Task = {
  session_id: string;
  pattern_id: string;
  title: string;
  skill: string;
  level: string;
  story: string;
  requirements: string;
  starter: string;
  time_limit_minutes: number;
  started_at: string;
  deadline: string;
  status: "open" | "submitted" | "expired";
};

/** The candidate view. Never `view=full`: its failure details quote the hidden tests. */
export type CandidateResult = {
  session_id: string;
  outcome: "passed" | "tests_failed" | "import_error" | "timeout" | "resource_limit";
  score: { passed: number; total: number; core_passed: number; core_total: number; twist_passed: number; twist_total: number } | null;
  tests: { name: string; group: "core" | "twist"; passed: boolean }[];
  time_used_seconds: number;
  note: string | null;
};
