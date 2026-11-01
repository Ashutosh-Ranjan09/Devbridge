import type { ReactNode } from "react";

import { lineKey, type Marks, type MarkView } from "@/lib/review";
import { CANDIDATE_TEXT, type Report } from "@/lib/types";

import { Icon } from "./icons";

/** A developer's own CV report, drawn rather than told: M5's buckets as a chart, its
 * checks by area, then the lines themselves in M5's words. Rule ids, coverage and the
 * model's name are left out. The recruiter and admin pages read the full ReportView.
 * Counts of M5's own lists only: no verdict, no total, no score. */
export function CvReport({ report, marks, alsoChecked }: { report: Report; marks: Marks; alsoChecked: string[] }) {
  const findings = new Map(report.findings.discrepancies.map((f) => [f.finding_id, f]));
  const claims = new Map(report.claim_graph.claims.map((c) => [c.claim_id, c]));
  const b = report.findings.buckets;
  const sources = [...new Set((report.provenance?.sources_queried ?? []).map((s) => s.source))];
  const typed = Object.entries(report.provenance?.typed_handles ?? {});
  const attention = b.contradicted.length + b.needs_context.length;

  const slices = [
    { label: "Verified", count: b.verified.length, tone: "ok" },
    { label: "Didn't match", count: b.contradicted.length, tone: "danger" },
    { label: "Worth explaining", count: b.needs_context.length, tone: "warn" },
    { label: "Couldn't check", count: b.not_evaluated.length, tone: "muted" },
  ] as const;

  return (
    <div className="space-y-6">
      {/* Overview: the buckets as a ring, and where the checks went. */}
      <section className="grid grid-cols-1 gap-6 rounded-2xl border border-line bg-panel p-5 sm:p-6 md:grid-cols-[auto_1fr] md:items-center">
        <div className="flex items-center gap-6">
          <Donut slices={slices} centre={b.verified.length} caption="verified" />
          <ul className="space-y-2 text-sm">
            {slices.map((s) => (
              <li key={s.label} className="flex items-center gap-2.5">
                <Dot tone={s.tone} /> <span className="w-6 font-semibold tabular-nums">{s.count}</span>
                <span className="text-muted">{s.label}</span>
              </li>
            ))}
          </ul>
        </div>
        {sources.length > 0 && (
          <div className="md:border-l md:border-line md:pl-6">
            <p className="mb-3 text-xs font-semibold tracking-wider text-muted uppercase">Checked against</p>
            <div className="flex flex-wrap gap-2">
              {sources.map((s) => {
                const src = SOURCE[s] ?? { label: s.replaceAll("_", " "), icon: "Check" as const };
                const Glyph = Icon[src.icon];
                return (
                  <span key={s} className="flex items-center gap-2 rounded-xl border border-line bg-background px-3 py-2 text-sm font-medium">
                    <Glyph className="size-4 text-accent" /> {src.label}
                    <Icon.Check className="size-3.5 text-ok" />
                  </span>
                );
              })}
            </div>
            {typed.length > 0 && (
              <p className="mt-3 text-xs text-muted">
                Using your usernames: {typed.map(([p, h]) => `${p} ${h}`).join(", ")}
              </p>
            )}
          </div>
        )}
      </section>

      <ByArea report={report} />

      {(report.status === "completed_degraded" || report.document?.ingest_method === "ocr") && (
        <p className="flex items-center gap-2 rounded-xl border border-highlight/40 bg-highlight/10 px-4 py-3 text-sm">
          <Icon.Clock className="size-4 shrink-0" />
          {report.status === "completed_degraded"
            ? "Some sources didn't answer. Checking again may confirm more."
            : "Read from an image, so some checks couldn't run. A text PDF works best."}
        </p>
      )}

      {attention > 0 && (
        <section>
          <Heading tone="danger" title="Needs your attention" count={attention} />
          <div className="grid grid-cols-1 gap-3">
            {b.contradicted.map((id) => {
              const f = findings.get(id);
              if (!f) return null;
              const quotes = f.claim_refs.map((r) => claims.get(r)?.provenance.verbatim).filter((q) => q !== undefined);
              return (
                <Issue key={id} tone="danger" tag="Didn't match" text={f.explanation} quotes={quotes}
                  mark={marks.get(lineKey("contradicted", id))} />
              );
            })}
            {b.needs_context.map((id) => {
              const f = findings.get(id);
              if (!f) return null;
              const q = f.params[CANDIDATE_TEXT];
              return (
                <Issue key={id} tone="warn" tag="Worth explaining" text={f.explanation}
                  quotes={Array.isArray(q) ? q.map(String) : []} why={f.innocent_explanation}
                  mark={marks.get(lineKey("needs_context", id))} />
              );
            })}
          </div>
        </section>
      )}

      <section>
        <Heading tone="ok" title="Verified" count={b.verified.length} />
        {b.verified.length === 0 ? (
          <p className="rounded-2xl border border-line bg-panel p-5 text-sm text-muted">Nothing could be confirmed this time.</p>
        ) : (
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {b.verified.map((v, i) => {
              const Glyph = Icon[sourceOf(v)];
              return (
                <li key={v} className="flex gap-3 rounded-2xl border border-line bg-panel p-4">
                  <span className="relative grid size-9 shrink-0 place-items-center rounded-xl bg-ok/10 text-ok">
                    <Glyph className="size-[18px]" />
                    <span className="absolute -right-1 -bottom-1 grid size-4 place-items-center rounded-full bg-ok text-white ring-2 ring-panel">
                      <Icon.Check className="size-2.5" />
                    </span>
                  </span>
                  <div className="min-w-0 text-sm leading-snug">
                    {v}
                    <Marked mark={marks.get(lineKey("verified", i))} />
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {b.not_evaluated.length > 0 && (
        <section>
          <Heading tone="muted" title="Couldn't check" count={b.not_evaluated.length} />
          <ul className="flex flex-wrap gap-2">
            {b.not_evaluated.map((n, i) => (
              <li key={n} className="rounded-xl border border-dashed border-line bg-panel px-3 py-2 text-sm text-muted">
                {n}
                <Marked mark={marks.get(lineKey("not_evaluated", i))} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="space-y-3">
        {report.narrative && (
          <Fold title="Full written summary">
            <p className="text-sm leading-relaxed whitespace-pre-line">{report.narrative.summary}</p>
          </Fold>
        )}
        {alsoChecked.length > 0 && (
          <Fold title={`Also checked, nothing raised (${alsoChecked.length})`}>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted">{alsoChecked.map((l) => <li key={l}>{l}</li>)}</ul>
          </Fold>
        )}
        {b.out_of_scope.length > 0 && (
          <Fold title={`Self-declared, not checked (${b.out_of_scope.length})`}>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
              {b.out_of_scope.map((o, i) => <li key={o}>{o}<Marked mark={marks.get(lineKey("out_of_scope", i))} /></li>)}
            </ul>
          </Fold>
        )}
      </div>
    </div>
  );
}

/** M5's checks grouped by the family its rule ids name (rules.py: P, G, W, D), each a
 * bar of what came back: passed, flagged, or could not run. Inapplicable ones are left out. */
function ByArea({ report }: { report: Report }) {
  const areas = new Map<string, { passed: number; flagged: number; skipped: number }>();
  for (const o of report.findings.rule_outcomes) {
    if (o.status === "not_applicable") continue;
    const area = AREA[o.rule_id[0]] ? o.rule_id[0] : "?";
    const a = areas.get(area) ?? { passed: 0, flagged: 0, skipped: 0 };
    if (o.status === "clean") a.passed++;
    else if (o.status === "fired") a.flagged++;
    else a.skipped++;
    areas.set(area, a);
  }
  const rows = [...areas].sort(([x], [y]) => ORDER.indexOf(x) - ORDER.indexOf(y));
  if (!rows.length) return null;
  return (
    <section className="rounded-2xl border border-line bg-panel p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">By area</h2>
        <div className="flex gap-4 text-xs text-muted">
          <span className="flex items-center gap-1.5"><Dot tone="ok" /> Passed</span>
          <span className="flex items-center gap-1.5"><Dot tone="danger" /> Flagged</span>
          <span className="flex items-center gap-1.5"><Dot tone="muted" /> Couldn&apos;t run</span>
        </div>
      </div>
      <ul className="space-y-4">
        {rows.map(([key, a]) => {
          const area = AREA[key] ?? { label: "Other checks", icon: "Check" as const };
          const Glyph = Icon[area.icon];
          const total = a.passed + a.flagged + a.skipped;
          return (
            <li key={key} className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1.5 sm:grid-cols-[11rem_1fr_9.5rem]">
              <span className="flex items-center gap-2 text-sm font-medium">
                <Glyph className="size-4 text-accent" /> {area.label}
              </span>
              <span className="col-span-2 row-start-2 flex h-2.5 overflow-hidden rounded-full bg-line sm:col-span-1 sm:row-start-auto" aria-hidden>
                <span className="bg-ok" style={{ width: `${(a.passed / total) * 100}%` }} />
                <span className="bg-danger" style={{ width: `${(a.flagged / total) * 100}%` }} />
                <span className="bg-muted/40" style={{ width: `${(a.skipped / total) * 100}%` }} />
              </span>
              <span className="justify-self-end text-right text-xs whitespace-nowrap text-muted tabular-nums">
                {a.passed}/{total} passed{a.flagged ? ` · ${a.flagged} flagged` : ""}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const ORDER = ["P", "G", "W", "D", "?"];
const AREA: Record<string, { label: string; icon: "Spark" | "Code" | "Globe" | "File" }> = {
  P: { label: "Coding platforms", icon: "Spark" },
  G: { label: "GitHub", icon: "Code" },
  W: { label: "Live projects", icon: "Globe" },
  D: { label: "The CV itself", icon: "File" },
};

const SOURCE: Record<string, { label: string; icon: "Spark" | "Code" | "Globe" | "Building" }> = {
  codeforces: { label: "Codeforces", icon: "Spark" },
  leetcode: { label: "LeetCode", icon: "Spark" },
  codechef: { label: "CodeChef", icon: "Spark" },
  github: { label: "GitHub", icon: "Code" },
  http_probe: { label: "Live links", icon: "Globe" },
  aicte: { label: "AICTE registry", icon: "Building" },
};

/** An icon for a verified line, from the words in it; only a picture, never a meaning. */
function sourceOf(line: string): "Spark" | "Code" | "Globe" | "Building" | "File" {
  const l = line.toLowerCase();
  if (/codeforces|leetcode|codechef|rating|contest/.test(l)) return "Spark";
  if (/repositor|commit|github|fork|language/.test(l)) return "Code";
  if (/live|http|url|deploy|vercel|netlify/.test(l)) return "Globe";
  if (/institution|aicte|university|college|faculty|supervisor/.test(l)) return "Building";
  return "File";
}

type Tone = "ok" | "danger" | "warn" | "muted";
const DOT: Record<Tone, string> = { ok: "bg-ok", danger: "bg-danger", warn: "bg-highlight", muted: "bg-muted/50" };
const STROKE: Record<Tone, string> = { ok: "stroke-ok", danger: "stroke-danger", warn: "stroke-highlight", muted: "stroke-muted/40" };

function Dot({ tone }: { tone: Tone }) {
  return <span className={`inline-block size-2.5 shrink-0 rounded-full ${DOT[tone]}`} aria-hidden />;
}

/** The buckets as arcs of one ring, in M5's order; the verified count in the middle. */
function Donut({ slices, centre, caption }: { slices: readonly { label: string; count: number; tone: Tone }[]; centre: number; caption: string }) {
  const r = 15.5;
  const c = 2 * Math.PI * r;
  const sum = slices.reduce((n, s) => n + s.count, 0);
  const gap = sum > 1 ? 0.8 : 0;
  let at = 0;
  return (
    <div className="relative size-32 shrink-0" role="img"
      aria-label={slices.map((s) => `${s.count} ${s.label.toLowerCase()}`).join(", ")}>
      <svg viewBox="0 0 36 36" className="size-full -rotate-90">
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="4" className="stroke-line" />
        {sum > 0 && slices.filter((s) => s.count).map((s) => {
          const len = (s.count / sum) * c;
          const arc = (
            <circle key={s.label} cx="18" cy="18" r={r} fill="none" strokeWidth="4" className={STROKE[s.tone]}
              strokeDasharray={`${Math.max(len - gap, 0.1)} ${c}`} strokeDashoffset={-at} />
          );
          at += len;
          return arc;
        })}
      </svg>
      <span className="absolute inset-0 grid place-items-center text-center leading-none">
        <span><span className="block text-3xl font-bold">{centre}</span><span className="mt-1 block text-xs text-muted">{caption}</span></span>
      </span>
    </div>
  );
}

function Heading({ tone, title, count }: { tone: Tone; title: string; count: number }) {
  return (
    <h2 className="mb-3 flex items-center gap-2 font-semibold">
      <Dot tone={tone} /> {title}
      <span className="rounded-full bg-panel px-2 py-0.5 text-xs font-medium text-muted ring-1 ring-line">{count}</span>
    </h2>
  );
}

function Issue({ tone, tag, text, quotes, why, mark }: {
  tone: "danger" | "warn"; tag: string; text: string; quotes: string[]; why?: string | null; mark?: MarkView;
}) {
  return (
    <article className={`rounded-2xl border border-l-4 border-line bg-panel p-4 sm:p-5 ${tone === "danger" ? "border-l-danger" : "border-l-highlight"}`}>
      <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${tone === "danger" ? "bg-danger/10 text-danger" : "bg-highlight/15 text-[#b45309] dark:text-highlight"}`}>
        {tag}
      </span>
      <p className="mt-2 font-medium leading-snug">{text}</p>
      {quotes.map((q) => (
        <p key={q} className="mt-2 rounded-lg bg-background px-3 py-2 text-sm">
          <span className="text-muted">Your CV: </span>“{q}”
        </p>
      ))}
      {why && (
        <details className="group mt-2 text-sm">
          <summary className="cursor-pointer list-none text-muted hover:text-foreground">
            <span className="inline-flex items-center gap-1">Why this may be fine <Icon.Chevron className="size-3.5 transition group-open:rotate-180" /></span>
          </summary>
          <p className="mt-1 text-muted">{why}</p>
        </details>
      )}
      <Marked mark={mark} />
    </article>
  );
}

function Fold({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group rounded-2xl border border-line bg-panel px-5 py-4">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium">
        {title} <Icon.Chevron className="size-4 shrink-0 text-muted transition group-open:rotate-180" />
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

/** An admin's mark, said as an admin's: never shown as if M5 had found it. */
function Marked({ mark }: { mark?: MarkView }) {
  if (!mark) return null;
  return (
    <p className="mt-1.5 text-xs">
      <span className={`font-semibold ${mark.mark === "VERIFIED" ? "text-ok" : "text-danger"}`}>
        Admin: {mark.mark === "VERIFIED" ? "verified" : "not verified"}
      </span>
      <span className="text-muted"> · {mark.note}</span>
    </p>
  );
}
