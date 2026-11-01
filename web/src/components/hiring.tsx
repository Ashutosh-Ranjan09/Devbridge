"use client";

import Link from "next/link";
import { useState } from "react";

import type { ApplicationStatus, Outcome } from "@/generated/prisma/enums";

import { OrgBadge, OutcomeChip } from "./dashboard";
import { Icon } from "./icons";

/** The recruiter's two lists: their jobs, and one job's applicants. Both narrow by
 * words the recruiter types or a filter they press; neither ever orders people by a skill. */

type Stages = Record<ApplicationStatus, number>;

export type JobRow = {
  id: string; title: string; org: string; created: string;
  state: "draft" | "listed" | "closed" | "unknown";
  must: string[]; stages: Stages;
};

const STATE: Record<JobRow["state"], { label: string; className: string }> = {
  draft: { label: "Draft", className: "bg-highlight/15 text-[#b45309] dark:text-highlight" },
  listed: { label: "Listed", className: "bg-ok/10 text-ok" },
  closed: { label: "Not listed", className: "bg-background text-muted ring-1 ring-line" },
  unknown: { label: "Status unavailable", className: "bg-background text-muted ring-1 ring-line" },
};

export function JobState({ state }: { state: JobRow["state"] }) {
  const s = STATE[state];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold whitespace-nowrap ${s.className}`}>
      {state === "listed" && <span className="size-1.5 rounded-full bg-current" aria-hidden />}{s.label}
    </span>
  );
}

const STAGE_ROW: { key: ApplicationStatus; label: string; className: string }[] = [
  { key: "APPLIED", label: "New", className: "bg-highlight" },
  { key: "ASSESSMENT_SENT", label: "Testing", className: "bg-accent/45" },
  { key: "SUBMITTED", label: "To review", className: "bg-accent" },
  { key: "DECIDED", label: "Decided", className: "bg-muted/50" },
];

export function JobBoard({ jobs }: { jobs: JobRow[] }) {
  const [q, setQ] = useState("");
  const [show, setShow] = useState<"all" | JobRow["state"]>("all");
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = jobs.filter((j) =>
    (show === "all" || j.state === show) && words.every((w) => [j.title, j.org, ...j.must].join(" ").toLowerCase().includes(w)));
  const tabs = [["all", "All"], ["listed", "Listed"], ["draft", "Drafts"], ["closed", "Not listed"]] as const;

  if (!jobs.length) {
    return (
      <div className="rounded-2xl border border-dashed border-line bg-panel px-6 py-14 text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-full bg-accent/10 text-accent"><Icon.Briefcase className="size-6" /></span>
        <p className="mt-4 text-lg font-semibold">Post your first job</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted">
          Paste a job description. We propose the skills it asks for, you confirm them, and applicants are checked against them.
        </p>
        <Link href="/recruiter/jobs/new" className="mt-5 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent hover:brightness-110">
          Start from a job description
        </Link>
      </div>
    );
  }
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="relative w-full min-w-0 sm:w-auto sm:flex-1">
          <span className="sr-only">Search jobs</span>
          <Search />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by title or skill"
            className="h-11 w-full rounded-xl border border-line bg-panel pr-4 pl-10 text-sm outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/15" />
        </label>
        <div className="flex max-w-full overflow-x-auto rounded-xl border border-line bg-panel p-1 text-sm" role="group" aria-label="Show">
          {tabs.map(([v, label]) => {
            const n = v === "all" ? jobs.length : jobs.filter((j) => j.state === v).length;
            return (
              <button key={v} type="button" onClick={() => setShow(v)} aria-pressed={show === v}
                className={`rounded-lg px-3 py-1.5 font-medium whitespace-nowrap transition ${show === v ? "bg-accent text-on-accent" : "text-muted hover:text-foreground"}`}>
                {label} <span className="opacity-70">{n}</span>
              </button>
            );
          })}
        </div>
      </div>
      {shown.length === 0
        ? <p className="rounded-2xl border border-dashed border-line bg-panel px-6 py-10 text-center text-sm text-muted">No jobs match.</p>
        : <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2">{shown.map((j) => <JobCard key={j.id} job={j} />)}</ul>}
    </div>
  );
}

function JobCard({ job }: { job: JobRow }) {
  const total = Object.values(job.stages).reduce((a, b) => a + b, 0);
  return (
    <li>
      <Link href={`/recruiter/jobs/${job.id}`}
        className="group flex h-full flex-col rounded-2xl border border-line bg-panel p-5 transition hover:border-accent/50 hover:shadow-sm sm:p-6">
        <div className="flex items-start gap-3">
          <OrgBadge name={job.org} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-lg font-semibold group-hover:text-accent">{job.title}</p>
            <p className="text-sm text-muted">{job.org} · posted {job.created}</p>
          </div>
          <JobState state={job.state} />
        </div>
        {job.must.length > 0 && (
          <ul className="mt-4 flex flex-wrap gap-1.5" aria-label="Must-haves">
            {job.must.slice(0, 5).map((m) => <li key={m} className="rounded-md bg-background px-2 py-0.5 text-xs font-medium ring-1 ring-line">{m}</li>)}
            {job.must.length > 5 && <li className="px-1 text-xs text-muted">+{job.must.length - 5}</li>}
          </ul>
        )}
        <div className="mt-auto pt-5">
          {job.state === "draft" ? (
            <p className="flex items-center justify-between gap-2 rounded-xl bg-highlight/10 px-3.5 py-2.5 text-sm">
              <span>Review the proposed skills to open it</span>
              <span className="flex items-center gap-1 font-semibold text-accent">Review <Icon.Arrow className="size-3.5" /></span>
            </p>
          ) : total === 0 ? (
            <p className="border-t border-line pt-4 text-sm text-muted">No applicants yet</p>
          ) : (
            <div className="border-t border-line pt-4">
              <div className="mb-2 flex items-baseline justify-between text-sm">
                <span><span className="font-semibold tabular-nums">{total}</span> <span className="text-muted">applicant{total > 1 ? "s" : ""}</span></span>
                {job.stages.APPLIED + job.stages.SUBMITTED > 0 && (
                  <span className="font-medium text-accent">{job.stages.APPLIED + job.stages.SUBMITTED} waiting on you</span>
                )}
              </div>
              <span className="flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden>
                {STAGE_ROW.map((s) => job.stages[s.key] > 0 && (
                  <span key={s.key} className={s.className} style={{ flexGrow: job.stages[s.key] }} />
                ))}
              </span>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                {STAGE_ROW.map((s) => (
                  <li key={s.key} className="flex items-center gap-1.5">
                    <span className={`size-2 rounded-full ${s.className}`} aria-hidden />{s.label} <span className="font-semibold text-foreground tabular-nums">{job.stages[s.key]}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Link>
    </li>
  );
}

// ── one job's applicants ─────────────────────────────────────────────────────

export type ApplicantRow = {
  id: string; name: string; applied: string; status: ApplicationStatus; outcome: Outcome | null;
  /** M6's shortlist: true clears every bar, false does not, null no evidence on record. */
  clearsAll: boolean | null;
  musts: { skill: string; label: string; clears: boolean | null; interval: [number, number] | null; inferred: boolean }[];
  /** The assessment module's total, once every task is finished; or "testing" until then. */
  test: { points: number; outOf: number } | "testing" | null;
};

const COLUMNS: { key: ApplicationStatus; title: string; hint: string; dot: string }[] = [
  { key: "APPLIED", title: "New", hint: "Send an assessment, or decide", dot: "bg-highlight" },
  { key: "ASSESSMENT_SENT", title: "Assessment sent", hint: "Waiting for the candidate", dot: "bg-accent/45" },
  { key: "SUBMITTED", title: "To review", hint: "Results are in", dot: "bg-accent" },
  { key: "DECIDED", title: "Decided", hint: "A decision was recorded", dot: "bg-muted/50" },
];

/** Applicants in name order, as a board by stage or as a list. "Clears every bar" is M6's
 * answer, and filtering by it is the recruiter's choice, off until pressed. */
export function ApplicantBoard({ jobId, applicants, shortlistNote }: { jobId: string; applicants: ApplicantRow[]; shortlistNote: string | null }) {
  const [view, setView] = useState<"board" | "list">("board");
  const [q, setQ] = useState("");
  const [clear, setClear] = useState(false);
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = applicants.filter((a) => (!clear || a.clearsAll === true) && words.every((w) => a.name.toLowerCase().includes(w)));
  const href = (a: ApplicantRow) => `/recruiter/jobs/${jobId}/applicants/${a.id}`;

  if (!applicants.length) {
    return (
      <div className="rounded-2xl border border-dashed border-line bg-panel px-6 py-14 text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-full bg-accent/10 text-accent"><Icon.User className="size-6" /></span>
        <p className="mt-4 font-semibold">No applicants yet</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted">Developers who apply show up here, with their verified skills beside each name.</p>
      </div>
    );
  }
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="relative w-full min-w-0 sm:w-auto sm:flex-1">
          <span className="sr-only">Search applicants</span>
          <Search />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name"
            className="h-10 w-full rounded-xl border border-line bg-panel pr-4 pl-10 text-sm outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/15" />
        </label>
        <button type="button" onClick={() => setClear(!clear)} aria-pressed={clear}
          className={`flex h-10 items-center gap-2 rounded-xl border px-3.5 text-sm font-medium transition ${clear ? "border-accent bg-accent/10 text-accent" : "border-line bg-panel text-muted hover:text-foreground"}`}>
          <Icon.Check className="size-4" /> Clears every bar
        </button>
        <div className="flex rounded-xl border border-line bg-panel p-1 text-sm" role="group" aria-label="View">
          {(["board", "list"] as const).map((v) => (
            <button key={v} type="button" onClick={() => setView(v)} aria-pressed={view === v}
              className={`rounded-lg px-3 py-1 font-medium capitalize transition ${view === v ? "bg-accent text-on-accent" : "text-muted hover:text-foreground"}`}>
              {v}
            </button>
          ))}
        </div>
      </div>
      <p className="mb-4 text-xs text-muted">In name order.{shortlistNote && ` ${shortlistNote}`}</p>

      {view === "board" ? (
        <div className="-mx-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0">
          <div className="grid min-w-[880px] grid-cols-4 gap-4">
            {COLUMNS.map((c) => {
              const here = shown.filter((a) => a.status === c.key);
              return (
                <section key={c.key} className="flex flex-col rounded-2xl bg-line/40 p-3 dark:bg-white/[0.03]" aria-label={c.title}>
                  <header className="mb-3 px-1">
                    <p className="flex items-center gap-2 font-semibold">
                      <span className={`size-2.5 rounded-full ${c.dot}`} aria-hidden />{c.title}
                      <span className="ml-auto rounded-full bg-panel px-2 text-xs font-semibold text-muted tabular-nums ring-1 ring-line">{here.length}</span>
                    </p>
                    <p className="mt-0.5 text-xs text-muted">{c.hint}</p>
                  </header>
                  <ul className="space-y-2.5">
                    {here.map((a) => <ApplicantCard key={a.id} a={a} href={href(a)} />)}
                    {here.length === 0 && <li className="rounded-xl border border-dashed border-line px-3 py-6 text-center text-xs text-muted">Nobody here</li>}
                  </ul>
                </section>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-line bg-panel">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-line text-xs tracking-wide text-muted uppercase">
              <tr><th className="px-4 py-3 font-medium">Applicant</th><th className="px-4 font-medium">Stage</th><th className="px-4 font-medium">Must-haves</th><th className="px-4 font-medium">Assessment</th></tr>
            </thead>
            <tbody>
              {shown.map((a) => (
                <tr key={a.id} className="border-t border-line align-top first:border-0 hover:bg-background/60">
                  <td className="px-4 py-3">
                    <Link href={href(a)} className="flex items-center gap-3 font-semibold hover:text-accent">
                      <Avatar name={a.name} />
                      <span>{a.name}<span className="block text-xs font-normal text-muted">Applied {a.applied}</span></span>
                    </Link>
                  </td>
                  <td className="px-4 py-3">{a.outcome ? <OutcomeChip outcome={a.outcome} /> : <span className="flex items-center gap-2 whitespace-nowrap"><span className={`size-2 rounded-full ${COLUMNS.find((c) => c.key === a.status)?.dot}`} />{COLUMNS.find((c) => c.key === a.status)?.title}</span>}</td>
                  <td className="px-4 py-3"><MustList a={a} /></td>
                  <td className="px-4 py-3 whitespace-nowrap"><TestCell test={a.test} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && <p className="px-4 py-8 text-center text-sm text-muted">Nobody matches.</p>}
        </div>
      )}
    </div>
  );
}

function ApplicantCard({ a, href }: { a: ApplicantRow; href: string }) {
  return (
    <li>
      <Link href={href} className="block rounded-xl border border-line bg-panel p-3.5 shadow-xs transition hover:border-accent/50 hover:shadow-sm">
        <div className="flex items-center gap-2.5">
          <Avatar name={a.name} />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold">{a.name}</p>
            <p className="text-xs text-muted">Applied {a.applied}</p>
          </div>
        </div>
        {a.clearsAll !== null && a.musts.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1" aria-label="Must-haves">
            {a.musts.map((m) => <MustDot key={m.skill} m={m} />)}
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
          {a.outcome && <OutcomeChip outcome={a.outcome} />}
          {a.clearsAll === true && <span className="rounded-full bg-ok/10 px-2 py-0.5 font-semibold text-ok">Clears every bar</span>}
          {a.clearsAll === null && <span className="text-muted">No evidence on record</span>}
          {a.test && <span className="ml-auto"><TestCell test={a.test} /></span>}
        </div>
      </Link>
    </li>
  );
}

/** One must-have as M6 answered: ✓ clears, ✗ does not, · assessed but not filtered. */
function MustDot({ m }: { m: ApplicantRow["musts"][number] }) {
  const tone = m.clears === true ? "bg-ok/10 text-ok ring-ok/25" : m.clears === false ? "bg-danger/10 text-danger ring-danger/25" : "bg-background text-muted ring-line";
  const said = m.clears === true ? "clears the bar" : m.clears === false ? "does not clear the bar" : "assessed, not filtered";
  return (
    <span title={`${m.label}: ${said}${m.interval ? ` (${m.interval[0].toFixed(2)}–${m.interval[1].toFixed(2)})` : ", no evidence"}${m.inferred ? ", inferred" : ""}`}
      className={`inline-flex max-w-full items-center gap-1 truncate rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ${tone}`}>
      {m.clears === true ? "✓" : m.clears === false ? "✗" : "·"} {m.label}
    </span>
  );
}

function MustList({ a }: { a: ApplicantRow }) {
  if (a.clearsAll === null) return <span className="text-muted">No evidence on record</span>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {a.musts.map((m) => (
        <li key={m.skill}><MustDot m={m} />{m.interval && <span className="ml-1 font-mono text-[11px] text-muted">{m.interval[0].toFixed(2)}–{m.interval[1].toFixed(2)}</span>}</li>
      ))}
    </ul>
  );
}

function TestCell({ test }: { test: ApplicantRow["test"] }) {
  if (!test) return <span className="text-xs text-muted">—</span>;
  if (test === "testing") return <span className="flex items-center gap-1 text-xs text-muted"><Icon.Clock className="size-3.5" />In progress</span>;
  return (
    <span className="rounded-md bg-accent/10 px-2 py-0.5 text-xs font-semibold text-accent tabular-nums" title="Assessment total">
      Test {test.points}/{test.outOf}
    </span>
  );
}

export function Avatar({ name }: { name: string }) {
  const initials = name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return <span className="grid size-9 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-bold text-accent">{initials}</span>;
}

function Search() {
  return (
    <svg viewBox="0 0 24 24" className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
    </svg>
  );
}
