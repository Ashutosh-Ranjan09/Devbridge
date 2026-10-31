import Link from "next/link";
import { after } from "next/server";
import { type ReactNode, Suspense } from "react";

import { Refresh } from "@/components/candidate";
import { CvReport } from "@/components/cv-report";
import { LinkButton } from "@/components/dashboard";
import { Icon } from "@/components/icons";
import { myVerification, requireCandidate } from "@/lib/candidate";
import { alsoChecked, m5Rules } from "@/lib/m5";
import { marksFor } from "@/lib/review";
import { call, ServiceError } from "@/lib/services";
import { forwardReport } from "@/lib/sync";
import { day, when } from "@/lib/tasks";
import type { Report, Running } from "@/lib/types";

export default function VerificationPage({ params }: PageProps<"/candidate/cv/[id]">) {
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6">
      <Link href="/candidate/cv" className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-accent">
        <Icon.Arrow className="size-4 rotate-180" /> My CV
      </Link>
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-line" />}>
        <Verification params={params} />
      </Suspense>
    </main>
  );
}

async function Verification({ params }: { params: Promise<{ id: string }> }) {
  const me = await requireCandidate();
  const v = await myVerification(me.id, (await params).id);
  let answer: Report | Running;
  try {
    answer = await call<Report | Running>("m5", `/v1/verifications/${encodeURIComponent(v.id)}`);
  } catch (e) {
    // M5 without a database forgets its reports on restart; the evidence already reached
    // the skill graph, so only the report itself is gone.
    if (e instanceof ServiceError && e.status === 404) {
      return (
        <State icon="File" title="This report is no longer available"
          text={`The report for ${v.fileName} wasn't kept by the checking service.${v.sentToM6At ? " What it found is already in your skills." : ""} Check your CV again to get a new one.`}
          action={<LinkButton href="/candidate/cv">Check my CV again</LinkButton>} />
      );
    }
    if (e instanceof ServiceError) return <State icon="Clock" title="The report can't be loaded right now" text={e.message} />;
    throw e;
  }

  if (answer.status === "running") {
    return (
      <State icon="Clock" spin title={`Checking ${v.fileName}`}
        text={`Started ${when(answer.created_at)}. This takes about a minute, and this page updates by itself.`}>
        <Refresh seconds={4} />
        <ol className="mx-auto mt-6 max-w-xs space-y-2 text-left text-sm text-muted">
          {["Reading your CV", "Checking GitHub, coding platforms and live links", "Writing your report"].map((s) => (
            <li key={s} className="flex items-center gap-2"><span className="size-1.5 animate-pulse rounded-full bg-accent" /> {s}</li>
          ))}
        </ol>
      </State>
    );
  }
  if (answer.status === "failed") {
    return (
      <State icon="File" title={`${v.fileName} couldn't be checked`} text={answer.failure ?? "Something went wrong reading the file."}
        action={<LinkButton href="/candidate/cv">Try another file</LinkButton>} />
    );
  }
  if (!v.sentToM6At) {
    const report = answer;
    // After the response: a slow or absent M6 delays the evidence, never this page.
    after(() => forwardReport(v.id, report).catch(() => {}));
  }
  const [marks, rules] = await Promise.all([marksFor(v.id), m5Rules()]);
  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-center gap-4 rounded-2xl border border-line bg-panel p-5 sm:p-6">
        <span className="grid size-12 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent"><Icon.File className="size-6" /></span>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-bold tracking-tight sm:text-2xl">{v.fileName}</h1>
          <p className="text-sm text-muted">
            Checked {day(answer.valid_as_of)} · {v.sentToM6At ? "added to your skills" : "being added to your skills"}
          </p>
        </div>
        <LinkButton href="/candidate/skills">See my skills</LinkButton>
      </section>

      {v.note && (
        <section className="rounded-2xl border border-line bg-panel p-5 sm:p-6">
          <h2 className="font-semibold">Your note</h2>
          <p className="mt-0.5 text-xs text-muted">Shown to recruiters beside this report, as your own words.</p>
          <p className="mt-3 text-sm whitespace-pre-line">{v.note}</p>
        </section>
      )}

      <CvReport report={answer} marks={marks} alsoChecked={alsoChecked(answer, rules)} />

    </div>
  );
}

function State({ icon, title, text, action, spin, children }: {
  icon: "File" | "Clock"; title: string; text: string; action?: ReactNode; spin?: boolean; children?: ReactNode;
}) {
  const Glyph = Icon[icon];
  return (
    <section className="rounded-2xl border border-line bg-panel px-6 py-12 text-center">
      <span className="mx-auto grid size-14 place-items-center rounded-full bg-accent/10 text-accent">
        <Glyph className={`size-7 ${spin ? "animate-pulse" : ""}`} />
      </span>
      <h1 className="mt-4 text-xl font-bold tracking-tight">{title}</h1>
      <p className="mx-auto mt-2 max-w-md text-muted">{text}</p>
      {children}
      {action && <div className="mt-6">{action}</div>}
    </section>
  );
}
