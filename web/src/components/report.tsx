import type { ReactNode } from "react";

import { lineKey, type Marks, type MarkView } from "@/lib/review";
import { CANDIDATE_TEXT, type Report } from "@/lib/types";

import { Card } from "./ui";

/** M5's report, in M5's own order and words: the buckets are M5's, the explanations are
 * M5's, and nothing here adds a verdict, a colour scale or a total. It mirrors what
 * `cvv verify` prints. */
export function ReportView({ report, marks, review, mine = false }: {
  report: Report;
  /** The candidate reading their own report: "your CV". Anyone else reads "the CV". */
  mine?: boolean;
  /** People's marks beside M5's lines. M5's buckets and order are never changed by them. */
  marks?: Marks;
  /** The admin's form for one line; the admin area only. */
  review?: (key: string) => ReactNode;
}) {
  const under = (key: string) => <Reviewed mark={marks?.get(key)}>{review?.(key)}</Reviewed>;
  const findings = new Map(report.findings.discrepancies.map((f) => [f.finding_id, f]));
  const claims = new Map(report.claim_graph.claims.map((c) => [c.claim_id, c]));
  const { buckets } = report.findings;
  const c = report.coverage;
  const typedHandles = Object.entries(report.provenance?.typed_handles ?? {});
  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-muted">
          {report.claim_graph.claims.length} claims extracted · {c.rules_total} checks registered ·{" "}
          {c.rules_evaluated} evaluated · {c.rules_abstained} could not run · coverage{" "}
          {Math.round(c.coverage * 100)}%
        </p>
        <p className="mt-1 text-sm text-muted">
          Coverage describes the verification, not {mine ? "you" : "the candidate"}.
        </p>
        {typedHandles.length > 0 && (
          <p className="mt-2 text-sm">
            Accounts {mine ? "you" : "the candidate"} typed on upload, because the CV names none:{" "}
            {typedHandles.map(([platform, handle], i) => (
              <span key={platform}>{i > 0 && ", "}{platform} <code>{handle}</code></span>
            ))}
            .
          </p>
        )}
        {report.status === "completed_degraded" && (
          <p className="mt-2 text-sm">Some sources did not answer, so running it again may check more.</p>
        )}
        {report.document?.ingest_method === "ocr" && (
          <p className="mt-2 text-sm">
            Read by OCR from an image. Checks that match against reference tables abstain more often on
            such text; that is a limit of the scan, not a finding.
          </p>
        )}
        {report.narrative && (
          <div className="mt-4">
            <p className="whitespace-pre-line">{report.narrative.summary}</p>
            <p className="mt-1 text-xs text-muted">
              {report.narrative.fallback_used
                ? `Written from the findings by code: the model's summary was rejected (${report.narrative.rejected_because}).`
                : `Summary by ${report.narrative.model_id}, checked against the findings.`}
            </p>
          </div>
        )}
      </Card>

      <Bucket title="✓ Verified" empty="Nothing could be confirmed.">
        {buckets.verified.map((v, i) => <li key={v}>{v}{under(lineKey("verified", i))}</li>)}
      </Bucket>

      <Bucket title="✗ Contradicted" empty="Nothing checked contradicts the CV.">
        {buckets.contradicted.map((id) => {
          const f = findings.get(id);
          if (!f) return null;
          return (
            <li key={id}>
              <Rule id={f.rule_id} /> {f.explanation}
              {f.claim_refs.map((ref) => claims.get(ref)).filter((x) => x !== undefined).map((claim) => (
                <Quote key={claim.claim_id} label={mine ? "your CV says" : "the CV says"}>{claim.provenance.verbatim}</Quote>
              ))}
              {under(lineKey("contradicted", id))}
            </li>
          );
        })}
      </Bucket>

      <Bucket title="? Needs context" empty="Nothing to explain.">
        {buckets.needs_context.map((id) => {
          const f = findings.get(id);
          if (!f) return null;
          const quoted = f.params[CANDIDATE_TEXT];
          return (
            <li key={id}>
              <Rule id={f.rule_id} /> {f.explanation}
              {f.innocent_explanation && <p className="mt-1 text-sm text-muted">Benign reading: {f.innocent_explanation}</p>}
              {Array.isArray(quoted) && quoted.map((q) => <Quote key={String(q)} label="text">{String(q)}</Quote>)}
              {under(lineKey("needs_context", id))}
            </li>
          );
        })}
      </Bucket>

      <Bucket title="– Not evaluated" empty="Every check ran.">
        {buckets.not_evaluated.map((n, i) => <li key={n}>{n}{under(lineKey("not_evaluated", i))}</li>)}
      </Bucket>

      <Bucket title="□ Out of scope" empty="">
        {buckets.out_of_scope.map((o, i) => <li key={o}>{o}{under(lineKey("out_of_scope", i))}</li>)}
      </Bucket>

      <p className="text-sm text-muted">
        No overall score is produced, by design. This report states what was checked, what was not, and
        why. A person decides what it means.
      </p>
    </div>
  );
}

function Bucket({ title, empty, children }: { title: string; empty: string; children: ReactNode[] }) {
  return (
    <Card>
      <h2 className="mb-2 font-semibold">{title}</h2>
      {children.length ? <ul className="space-y-3">{children}</ul> : <p className="text-sm text-muted">{empty}</p>}
    </Card>
  );
}

/** A person's mark, said as theirs: never shown as if M5 had found it. */
function Reviewed({ mark, children }: { mark?: MarkView; children?: ReactNode }) {
  if (!mark && !children) return null;
  return (
    <div className="mt-1 text-sm">
      {mark && (
        <p>
          <span className={mark.mark === "VERIFIED" ? "text-ok" : "text-danger"}>
            {mark.mark === "VERIFIED" ? "✓ Marked verified" : "✗ Marked unverified"}
          </span>{" "}
          <span className="text-muted">by {mark.by}, {mark.at.toLocaleDateString("en-IN")}:</span> {mark.note}
        </p>
      )}
      {children}
    </div>
  );
}

function Rule({ id }: { id: string }) {
  return <code className="text-xs text-muted">[{id}]</code>;
}

/** Text from the CV itself. React escapes it; it is never parsed as markup. */
function Quote({ label, children }: { label: string; children: string }) {
  return (
    <p className="mt-1 text-sm">
      <span className="text-muted">{label}: </span>
      <q className="font-mono">{children}</q>
    </p>
  );
}
