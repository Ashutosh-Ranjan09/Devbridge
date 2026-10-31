import Link from "next/link";
import { after } from "next/server";
import { Suspense } from "react";

import { Refresh } from "@/components/candidate";

import { type ProofFile, ProofItem, ReplaceCv, UploadCv } from "@/components/cv";
import { Chip, Panel } from "@/components/dashboard";
import { Icon } from "@/components/icons";
import { requireCandidate } from "@/lib/candidate";
import { db } from "@/lib/db";
import { extOf, readStored } from "@/lib/files";
import { call } from "@/lib/services";
import { forwardReport } from "@/lib/sync";
import { day } from "@/lib/tasks";
import type { Claim, Report, Running } from "@/lib/types";

/** One CV per candidate: the newest is theirs, shown as the file itself, with the
 * documents that back what no source can check beside it. Skills are on My skills. */
export default function CvPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <Suspense fallback={<div className="h-[70vh] animate-pulse rounded-2xl bg-line" />}>
        <Cv />
      </Suspense>
    </main>
  );
}

async function Cv() {
  const me = await requireCandidate();
  const [c, cv] = await Promise.all([
    db.candidate.findUniqueOrThrow({ where: { userId: me.id } }),
    db.verification.findFirst({ where: { candidateId: me.id }, orderBy: { createdAt: "desc" }, include: { proofs: { orderBy: { createdAt: "asc" } } } }),
  ]);
  const saved = Object.fromEntries(Object.entries({
    github: c.githubHandle, codeforces: c.codeforcesHandle, leetcode: c.leetcodeHandle, codechef: c.codechefHandle,
  }).filter(([, v]) => v !== null)) as Record<string, string>;

  if (!cv) {
    return (
      <div className="mx-auto max-w-2xl">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">My CV</h1>
        <p className="mt-1 mb-6 text-muted">Upload it once. We check it against your real work.</p>
        <Panel title="Upload your CV"><UploadCv saved={saved} again={false} /></Panel>
      </div>
    );
  }

  // M5 may have forgotten the report (no database): then only what needs proof is unknown.
  const [answer, stored] = await Promise.all([
    call<Report | Running>("m5", `/v1/verifications/${encodeURIComponent(cv.id)}`).catch(() => null),
    readStored("cv", cv.id, cv.fileName).then((b) => b !== null),
  ]);
  const report = answer && answer.status !== "running" ? answer : null;
  if (report && report.status !== "failed" && !cv.sentToM6At) {
    // After the response: a slow or absent M6 delays the evidence, never this page.
    after(() => forwardReport(cv.id, report).catch(() => {}));
  }
  const status = !answer ? null : answer.status === "running" ? "Checking…" : answer.status === "failed" ? "Couldn't be checked" : "Checked";
  const items = report ? needingProof(report.claim_graph.claims) : [];
  const byClaim = (id: string | null) => cv.proofs.filter((p) => p.claimId === id).map((p): ProofFile => ({ id: p.id, fileName: p.fileName }));
  const backed = items.filter((i) => byClaim(i.claimId).length > 0).length;
  const own = cv.proofs.filter((p) => !p.claimId || !items.some((i) => i.claimId === p.claimId));

  return (
    <div className="space-y-6">
      {answer?.status === "running" && <Refresh seconds={4} />}
      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">My CV</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <span className="truncate font-medium text-foreground">{cv.fileName}</span> · uploaded {day(cv.createdAt)}
            {status && <Chip tone={status === "Checked" ? "accent" : undefined}>{status}</Chip>}
            {report && <Link href={`/candidate/cv/${cv.id}`} className="font-medium text-accent hover:underline">Check report</Link>}
          </p>
        </div>
        <ReplaceCv saved={saved} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        {/* The CV itself. */}
        <section className="overflow-hidden rounded-2xl border border-line bg-panel">
          {stored && extOf(cv.fileName) === ".pdf" ? (
            <iframe src={`/files/cv/${cv.id}#view=FitH&navpanes=0`} title={`Your CV, ${cv.fileName}`} className="block h-[78vh] w-full bg-background" />
          ) : (
            <div className="flex h-[50vh] flex-col items-center justify-center gap-3 px-6 text-center lg:h-[78vh]">
              <span className="grid size-14 place-items-center rounded-full bg-accent/10 text-accent"><Icon.File className="size-7" /></span>
              <p className="font-semibold">{stored ? "Word files can't be previewed here" : "No preview for this upload"}</p>
              <p className="max-w-sm text-sm text-muted">
                {stored ? "Download it to view, or upload a PDF to see it here." : "It was uploaded before CVs were kept. Replace it to see it here."}
              </p>
              {stored && <a href={`/files/cv/${cv.id}`} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent">Download</a>}
            </div>
          )}
        </section>

        {/* What backs it. */}
        <aside className="space-y-6 lg:sticky lg:top-20 lg:self-start">
          <Panel title="Supporting proofs">
            {items.length > 0 ? (
              <>
                <div className="-mt-1 mb-4">
                  <div className="mb-1.5 flex justify-between text-sm">
                    <span className="text-muted">Recruiters trust what you can show</span>
                    <span className="font-semibold tabular-nums">{backed}/{items.length} backed</span>
                  </div>
                  <span className="block h-2 overflow-hidden rounded-full bg-line" aria-hidden>
                    <span className="block h-full rounded-full bg-accent" style={{ width: `${(backed / items.length) * 100}%` }} />
                  </span>
                </div>
                <ul className="space-y-3">
                  {items.map((i) => <ProofItem key={i.claimId} {...i} proofs={byClaim(i.claimId)} />)}
                </ul>
              </>
            ) : (
              <p className="-mt-1 mb-4 text-sm text-muted">
                {report ? "Nothing on your CV needs a document. Add one below if you'd like." : status === "Checking…" ? "Once the check finishes, anything that needs proof shows here." : "Add offer letters, certificates or anything else that backs your CV."}
              </p>
            )}
            <ul className="mt-3 space-y-3">
              {own.map((p) => <ProofItem key={p.id} claimId={p.claimId} kind="Other" title={p.label} proofs={[{ id: p.id, fileName: p.fileName }]} />)}
              <ProofItem claimId={null} kind="Other" title="Another document" sub="Anything else that backs your CV" proofs={[]} />
            </ul>
          </Panel>
          <p className="px-1 text-xs text-muted">
            Recruiters you apply to see these files, marked as uploaded by you.
          </p>
        </aside>
      </div>
    </div>
  );
}

type Need = { claimId: string; kind: "Experience" | "Certificate" | "Education"; title: string; sub?: string };

/** The CV's lines no outside source can confirm, where a document can: roles and
 * internships, certificates, and qualifications. In the CV's own words. */
function needingProof(claims: Claim[]): Need[] {
  const order = { employment: 0, certification: 1, education: 2 } as Record<string, number>;
  return claims
    .filter((c) => c.kind in order)
    .sort((a, b) => order[a.kind] - order[b.kind])
    .map((c): Need => {
      if (c.kind === "employment") {
        const type = c.employment_type === "internship" ? "Internship" : c.employment_type === "freelance" ? "Freelance" : "Role";
        return { claimId: c.claim_id, kind: "Experience", title: [c.title, c.org].filter(Boolean).join(" · ") || c.provenance.verbatim, sub: `${type} · offer or completion letter` };
      }
      if (c.kind === "certification") {
        return { claimId: c.claim_id, kind: "Certificate", title: c.title ?? c.provenance.verbatim, sub: c.issuer ? `${c.issuer} · the certificate` : "The certificate" };
      }
      return { claimId: c.claim_id, kind: "Education", title: [c.degree, c.org].filter(Boolean).join(" · ") || c.provenance.verbatim, sub: "Marksheet or degree certificate" };
    });
}
