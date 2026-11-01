import Link from "next/link";
import { after } from "next/server";
import { type ReactNode, Suspense } from "react";

import { StartPractice } from "@/components/candidate";
import { Chip, Empty, LinkButton, Panel } from "@/components/dashboard";
import { Icon } from "@/components/icons";
import { ScoreRing } from "@/components/score";
import { type GraphNode, SkillGraph } from "@/components/skill-graph";
import { myPractice, requireCandidate } from "@/lib/candidate";
import { db } from "@/lib/db";
import { call, ServiceError } from "@/lib/services";
import { evidenceOf, outOf100, skillCatalogue } from "@/lib/skills";
import { forwardPending } from "@/lib/sync";
import { day, PRACTISED } from "@/lib/tasks";
import type { Explanation, Pattern, Profile, Skill } from "@/lib/types";

export default function SkillsPage({ searchParams }: PageProps<"/candidate/skills">) {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-line" />}>
        <Skills searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Skills({ searchParams }: { searchParams: PageProps<"/candidate/skills">["searchParams"] }) {
  const me = await requireCandidate();
  const graph = (await searchParams).view === "graph";
  const pending =
    (await db.verification.count({ where: { candidateId: me.id, sentToM6At: null } })) +
    (await db.assessment.count({ where: { candidateId: me.id, sentToM6At: null } }));
  if (pending) after(() => forwardPending(me.id));

  let profile: Profile | null = null;
  try {
    profile = await call<Profile>("m6", `/developers/${encodeURIComponent(me.subjectRef)}/profile`);
  } catch (e) {
    // 404 is "no evidence on record": not a low score, and must not read as one.
    if (!(e instanceof ServiceError && e.status === 404)) {
      if (e instanceof ServiceError) return <Panel title="Your skills"><p className="text-muted">{e.message}</p></Panel>;
      throw e;
    }
  }
  const [catalogue, patterns, practised] = await Promise.all([
    skillCatalogue(),
    call<Pattern[]>("assess", "/v1/patterns").catch(() => [] as Pattern[]),
    myPractice(me.id),
  ]);
  const label = catalogue.label;
  const practice = new Set(patterns.map((p) => p.skill));
  // By name: the page lists skills, it does not rank them.
  const byName = (a: Skill, b: Skill) => label(a.skill_id).localeCompare(label(b.skill_id));
  const all = profile?.skills ?? [];
  const direct = all.filter((s) => !s.inferred).sort(byName);
  const estimated = all.filter((s) => s.inferred).sort(byName);

  const head = (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Your skills</h1>
        <p className="mt-1 max-w-2xl text-muted">Scored out of 100 from your CV, your public work and your assessments.</p>
      </div>
      {all.length > 0 && (
        <div className="flex rounded-xl border border-line bg-panel p-1 text-sm" role="group" aria-label="View">
          {([["Cards", "/candidate/skills"], ["Graph", "/candidate/skills?view=graph"]] as const).map(([name, href]) => {
            const on = (name === "Graph") === graph;
            return (
              <Link key={name} href={href} aria-current={on ? "page" : undefined}
                className={`rounded-lg px-4 py-1.5 font-medium transition ${on ? "bg-accent text-on-accent" : "text-muted hover:text-foreground"}`}>
                {name}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );

  if (graph && all.length > 0) {
    // Each skill's evidence, for the panel a click opens. One call per skill, only here.
    const explained = await Promise.all(all.map((s) =>
      call<Explanation>("m6", `/developers/${encodeURIComponent(me.subjectRef)}/skills/${encodeURIComponent(s.skill_id)}/explain`).catch(() => null)));
    const nodes: GraphNode[] = all.map((s, i) => ({
      id: s.skill_id, label: label(s.skill_id), score: s.score, inferred: s.inferred,
      tier: s.volatility_tier ?? catalogue.tier(s.skill_id) ?? "other",
      from: s.propagated?.from_skill_id ?? null,
      evidence: [...(explained[i]?.contributions ?? [])].sort((a, b) => b.weight - a.weight).map((c) => {
        const k = evidenceOf(c.kind);
        return { label: k.label, detail: k.detail, date: day(c.occurred_at), against: !!k.against };
      }),
    })).sort((a, b) => a.label.localeCompare(b.label));
    return (
      <div className="space-y-6">
        {head}
        <SkillGraph nodes={nodes} links={catalogue.edges} />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {head}
      {pending > 0 && (
        <p className="flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/5 px-4 py-3 text-sm">
          <Icon.Clock className="size-4 shrink-0 text-accent" />
          Your latest CV or assessment is still being added. Your scores will update in a moment.
        </p>
      )}

      {all.length === 0 ? (
        <Panel title="No skills yet">
          <Empty
            icon="Spark" title="Your skills will show up here"
            text="Upload your CV to have it verified, or take a practice task. Every piece of evidence adds to your scores."
            action={<div className="flex gap-3"><LinkButton href="/candidate/cv">Upload CV</LinkButton></div>}
          />
        </Panel>
      ) : (
        <>
          <section>
            <SectionHead title="Backed by evidence" count={direct.length} />
            <Grid>
              {direct.map((s) => (
                <SkillCard key={s.skill_id} skill={s} name={label(s.skill_id)} practice={practice.has(s.skill_id)}
                  note={`${s.evidence_count} piece${s.evidence_count === 1 ? "" : "s"} of evidence`} />
              ))}
            </Grid>
          </section>
          {estimated.length > 0 && (
            <section>
              <SectionHead title="Estimated from related skills" count={estimated.length}
                hint="You have no direct evidence for these yet. Add some to turn an estimate into a proven score." />
              <Grid>
                {estimated.map((s) => (
                  <SkillCard key={s.skill_id} skill={s} name={label(s.skill_id)} practice={practice.has(s.skill_id)}
                    note={s.propagated ? `From your ${label(s.propagated.from_skill_id)} evidence` : "Estimated"} />
                ))}
              </Grid>
            </section>
          )}
        </>
      )}

      {patterns.length > 0 && (
        <Panel title="Boost a score with a practice task">
          <p className="-mt-2 mb-4 text-sm text-muted">
            A timed coding task, like the ones companies send. Passing one is among the strongest evidence a skill can get.
          </p>
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {patterns.map((p) => {
              const mine = practised.get(p.id);
              return (
                <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
                  <div className="min-w-0">
                    <p className="font-medium">{p.title}</p>
                    <p className="mt-0.5 text-sm text-muted">Improves {label(p.skill)} · {p.level} · {p.time_limit_minutes} min</p>
                  </div>
                  {mine ? <LinkButton href={`/candidate/assessments/${mine.id}`}>{PRACTISED[mine.status]}</LinkButton> : <StartPractice patternId={p.id} />}
                </li>
              );
            })}
          </ul>
        </Panel>
      )}
    </div>
  );
}

function SectionHead({ title, count, hint }: { title: string; count: number; hint?: string }) {
  return (
    <div className="mb-4">
      <h2 className="flex items-center gap-2 font-semibold">
        {title} <span className="rounded-full bg-line px-2 py-0.5 text-xs font-medium text-muted">{count}</span>
      </h2>
      {hint && <p className="mt-1 text-sm text-muted">{hint}</p>}
    </div>
  );
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">{children}</div>;
}

function SkillCard({ skill, name, note, practice }: { skill: Skill; name: string; note: string; practice: boolean }) {
  return (
    <Link href={`/candidate/skills/${encodeURIComponent(skill.skill_id)}`}
      className="group flex items-center gap-4 rounded-2xl border border-line bg-panel p-4 transition hover:border-accent hover:shadow-sm">
      <ScoreRing value={outOf100(skill.score)} size={56} label={`${name}: ${outOf100(skill.score)} out of 100`} />
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold">{name}</p>
        <p className="truncate text-sm text-muted">{note}</p>
        {practice && <div className="mt-1.5"><Chip tone="accent">Practice task available</Chip></div>}
      </div>
      <Icon.Arrow className="size-4 shrink-0 text-muted transition group-hover:translate-x-0.5 group-hover:text-accent" />
    </Link>
  );
}
