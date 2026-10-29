import Link from "next/link";
import { after } from "next/server";
import { Suspense } from "react";

import { Interval } from "@/components/interval";
import { Card, Loading, Page } from "@/components/ui";
import { requireCandidate } from "@/lib/candidate";
import { db } from "@/lib/db";
import { call, ServiceError } from "@/lib/services";
import { forwardPending } from "@/lib/sync";
import type { Profile } from "@/lib/types";

export default function SkillsPage() {
  return (
    <Page title="Your skills">
      <Suspense fallback={<Loading />}>
        <Skills />
      </Suspense>
    </Page>
  );
}

async function Skills() {
  const me = await requireCandidate();
  const pending =
    (await db.verification.count({ where: { candidateId: me.id, sentToM6At: null } })) +
    (await db.assessment.count({ where: { candidateId: me.id, sentToM6At: null } }));
  if (pending) after(() => forwardPending(me.id));

  let profile: Profile | null = null;
  try {
    profile = await call<Profile>("m6", `/developers/${encodeURIComponent(me.subjectRef)}/profile`);
  } catch (e) {
    // 404 is "no evidence on record" — not a low score, and must not read as one.
    if (!(e instanceof ServiceError && e.status === 404)) {
      if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
      throw e;
    }
  }
  // Alphabetical: the page lists skills, it does not rank them.
  const skills = [...(profile?.skills ?? [])].sort((a, b) => a.skill_id.localeCompare(b.skill_id));
  return (
    <div className="space-y-4">
      {pending > 0 && (
        <p className="text-sm text-muted">{pending} item(s) not in your skill graph yet; they are being added.</p>
      )}
      <Card>
        {skills.length === 0 ? (
          <p>
            No evidence on record yet. <Link href="/candidate/cv" className="text-accent underline">Check a CV</Link> or{" "}
            <Link href="/candidate/assessments" className="text-accent underline">take an assessment</Link>.
          </p>
        ) : (
          <ul className="space-y-3">
            {skills.map((s) => (
              <li key={s.skill_id} className="grid gap-1 sm:grid-cols-[10rem_auto_1fr] sm:items-center sm:gap-4">
                <Link href={`/candidate/skills/${encodeURIComponent(s.skill_id)}`} className="text-accent underline">
                  {s.skill_id}
                </Link>
                <Interval interval={s.interval} mean={s.mean} />
                <span className="text-sm text-muted">
                  {s.evidence_count} evidence{s.inferred ? " · inferred from related skills" : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
        {profile && <p className="mt-4 text-sm text-muted">{profile.note}</p>}
      </Card>
      {profile && (
        <Card>
          <h2 className="mb-2 font-semibold">The shape of the evidence</h2>
          <p className="text-sm">{profile.integrity.note}</p>
          <ul className="mt-2 space-y-2">
            {profile.integrity.findings.map((f) => (
              <li key={f.check_id + f.summary}>
                {f.summary}
                {f.innocent_explanation && <p className="text-sm text-muted">Benign reading: {f.innocent_explanation}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
