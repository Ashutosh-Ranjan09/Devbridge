import Link from "next/link";
import { notFound } from "next/navigation";
import { type ReactNode, Suspense } from "react";

import { StartPractice } from "@/components/candidate";
import { Chip, Empty, LinkButton, Panel } from "@/components/dashboard";
import { Icon } from "@/components/icons";
import { ScoreRing } from "@/components/score";
import { myPractice, requireCandidate } from "@/lib/candidate";
import { db } from "@/lib/db";
import { call, ServiceError } from "@/lib/services";
import { evidenceOf, outOf100, skillLabels } from "@/lib/skills";
import { day, PRACTISED } from "@/lib/tasks";
import type { Explanation, Job, Pattern } from "@/lib/types";

/** One skill for its owner: the score, the evidence behind it in plain words, and what
 * would add more. How the number is computed stays with M6. */
export default function SkillPage({ params }: PageProps<"/candidate/skills/[skill]">) {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <Link href="/candidate/skills" className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-accent">
        <Icon.Arrow className="size-4 rotate-180" /> All skills
      </Link>
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-line" />}>
        <SkillDetail params={params} />
      </Suspense>
    </main>
  );
}

async function SkillDetail({ params }: { params: Promise<{ skill: string }> }) {
  const me = await requireCandidate();
  const { skill } = await params;
  let x: Explanation;
  try {
    x = await call<Explanation>("m6", `/developers/${encodeURIComponent(me.subjectRef)}/skills/${encodeURIComponent(skill)}/explain`);
  } catch (e) {
    if (e instanceof ServiceError && e.status === 404) notFound();
    if (e instanceof ServiceError) return <Panel title="This skill"><p className="text-muted">{e.message}</p></Panel>;
    throw e;
  }
  const openJobs = await db.job.findMany({ where: { open: true }, include: { org: true }, orderBy: { createdAt: "desc" } });
  const [label, patterns, practised, jobs] = await Promise.all([
    skillLabels(),
    call<Pattern[]>("assess", "/v1/patterns").catch(() => [] as Pattern[]),
    myPractice(me.id),
    Promise.all(openJobs.map((j) => call<Job>("assess", `/v1/jobs/${encodeURIComponent(j.id)}`).catch(() => null))),
  ]);
  const name = label(x.skill);
  const score = outOf100(x.score);
  const tasks = patterns.filter((p) => p.skill === x.skill);
  // Roles whose own listed skills name this one: the job's words, not a match on the person.
  const roles = openJobs.filter((_, i) => jobs[i]?.skills.some((s) => s.skill_id === x.skill)).slice(0, 3);
  // The evidence that moved the score most, first.
  const evidence = [...x.contributions].sort((a, b) => b.weight - a.weight);

  return (
    <div className="space-y-6">
      <section className="flex flex-col items-start gap-6 rounded-2xl border border-line bg-panel p-6 sm:flex-row sm:items-center sm:p-8">
        <ScoreRing value={score} size={112} label={`${name}: ${score} out of 100`} />
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{name}</h1>
          <p className="mt-2 max-w-xl text-muted">
            {x.propagated
              ? <>Estimated from your {label(x.propagated.from_skill_id)} evidence. You have no direct evidence for {name} yet, so adding some is the quickest way to raise this score.</>
              : <>Based on {x.evidence_count} piece{x.evidence_count === 1 ? "" : "s"} of evidence. More evidence, especially an assessment, raises and firms up the score.</>}
          </p>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Panel title="Your evidence">
            {evidence.length === 0 ? (
              <Empty icon="File" title="No direct evidence yet"
                text={`Nothing yet shows ${name} on its own. Use one of the ways on this page to add some.`} />
            ) : (
              <ul className="divide-y divide-line">
                {evidence.map((c, i) => {
                  const kind = evidenceOf(c.kind);
                  const Glyph = Icon[kind.icon];
                  return (
                    <li key={c.event_id} className="flex items-start gap-4 py-4 first:pt-0 last:pb-0">
                      <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${kind.against ? "bg-danger/10 text-danger" : "bg-accent/10 text-accent"}`}>
                        <Glyph className="size-5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-medium">{kind.label}</p>
                          {kind.against ? <Chip>Lowered this score</Chip> : i === 0 && evidence.length > 1 && <Chip tone="accent">Counts most</Chip>}
                        </div>
                        {kind.detail && <p className="mt-0.5 text-sm text-muted">{kind.detail}</p>}
                      </div>
                      <span className="shrink-0 text-sm whitespace-nowrap text-muted">{day(c.occurred_at)}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </div>

        <aside className="space-y-6">
          <Panel title="Improve this score">
            <ol className="space-y-5">
              {tasks.map((p) => {
                const mine = practised.get(p.id);
                return (
                  <Way key={p.id} icon="Code" title={`Take the “${p.title}” task`}
                    text={mine?.status === "submitted"
                      ? "You've done this one, and its result is already in your score. Each task can be practised once."
                      : `${cap(p.level)} · ${p.time_limit_minutes} min. Passing it is among the strongest evidence for ${name}.`}>
                    {mine ? <LinkButton href={`/candidate/assessments/${mine.id}`}>{PRACTISED[mine.status]}</LinkButton> : <StartPractice patternId={p.id} />}
                  </Way>
                );
              })}
              <Way icon="Upload" title="Show it in your work"
                text={`Put ${name} to work in a public GitHub project, or link a live project from your CV. Then check your CV again, adding your GitHub, Codeforces and LeetCode usernames.`}>
                <LinkButton href="/candidate/cv">Check my CV again</LinkButton>
              </Way>
              {roles.length > 0 && (
                <Way icon="Briefcase" title={`Roles asking for ${name}`}
                  text="Their assessment adds evidence, whatever the outcome.">
                  <ul className="w-full space-y-2">
                    {roles.map((j) => (
                      <li key={j.id}>
                        <Link href="/candidate/jobs" className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm transition hover:border-accent">
                          <span className="min-w-0"><span className="block truncate font-medium">{j.title}</span><span className="block text-xs text-muted">{j.org.name}</span></span>
                          <Icon.Arrow className="size-4 shrink-0 text-muted" />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </Way>
              )}
            </ol>
          </Panel>
        </aside>
      </div>
    </div>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function Way({ icon, title, text, children }: { icon: keyof typeof Icon; title: string; text: string; children: ReactNode }) {
  const Glyph = Icon[icon];
  return (
    <li className="flex gap-3">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent"><Glyph className="size-[18px]" /></span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        <p className="mt-0.5 text-sm text-muted">{text}</p>
        <div className="mt-3">{children}</div>
      </div>
    </li>
  );
}
