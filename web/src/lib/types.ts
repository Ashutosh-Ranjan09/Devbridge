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
    /** Every registered check, including those that did not fire. `note`: what a clean
     * check confirmed, printed under Verified (an M5 extension). */
    rule_outcomes: { rule_id: string; status: "fired" | "clean" | "abstained" | "error" | "not_applicable"; note?: string | null }[];
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
  /** typed_handles: usernames the candidate typed that M5 used, because the CV names none. */
  provenance?: { typed_handles?: Record<string, string> };
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
  // null until the candidate presses Start: read at leisure, the time limit measures nothing
  story: string | null;
  requirements: string | null;
  starter: string | null;
  time_limit_minutes: number;
  issued_at: string;
  start_by: string | null; // a job's task: the last moment to press Start
  started_at: string | null;
  deadline: string | null;
  status: "issued" | "open" | "submitted" | "expired";
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

// ── assessment: jobs ───────────────────────────────────────────────────────

export type JobSkill = {
  skill_id: string | null; // null: named in the JD, not on the shared list
  surface: string;
  quote: string;
  priority: "must" | "nice";
  bar: number | null;
  needs_review: boolean;
  assessable: boolean;
};

export type Job = {
  job_id: string;
  text: string;
  status: "proposed" | "confirmed";
  skills: JobSkill[];
  extracted_by: string;
  dropped_unquoted: number;
  confirmed_by: string | null;
  confirmed_at: string | null;
};

/** schemas/job-requirements.schema.json, passed to M6 unchanged. */
export type Requirements = { job_id: string; must: { skill_id: string; bar: number | null }[]; nice: string[] };

/** The full view of a result, for the person reading it: each failure's detail. */
export type FullResult = Omit<CandidateResult, "tests"> & {
  tests: { name: string; group: "core" | "twist"; passed: boolean; detail: string | null }[];
};

// ── M6: POST /shortlist?subject=… ──────────────────────────────────────────

export type SkillColumn = { interval: [number, number]; mean: number; evidence_count: number; inferred: boolean } | null;

export type ShortlistEntry = {
  subject_ref: string;
  must: Record<string, SkillColumn>;
  nice: Record<string, SkillColumn>;
  clears: Record<string, boolean | null>; // M6's own filter decision per must-have
};

export type Shortlist = {
  match: string;
  must: { skill_id: string; bar: number | null; filters: boolean }[];
  nice: string[];
  candidates: ShortlistEntry[]; // clear every bar
  others: ShortlistEntry[]; // asked about, do not
  no_evidence: string[];
  unknown_skills: string[];
  note: string;
};

// ── admin ───────────────────────────────────────────────────────────────────

/** M5's GET /v1/rules: the live catalogue of checks. */
export type Rule = { rule_id: string; version: string; tier: "decisive" | "attention" | "evidence_only"; scoring: boolean; summary: string };

/** M6's GET /quarantine: event id → skill names the ontology does not know. */
export type Quarantine = { count: number; quarantined: Record<string, string[]>; ontology_version: string };
