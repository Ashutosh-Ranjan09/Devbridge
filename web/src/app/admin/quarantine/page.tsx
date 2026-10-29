import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { requireRole } from "@/lib/auth";
import { call, ServiceError } from "@/lib/services";
import type { Quarantine } from "@/lib/types";

export default function QuarantinePage() {
  return (
    <Page title="Quarantine">
      <Suspense fallback={<Loading />}>
        <Held />
      </Suspense>
    </Page>
  );
}

/** Skill names that reached M6 in evidence but are not on the shared skill list. Each is
 * held per skill: the event still counts for its known skills. Growing the list is a
 * reviewed change to schemas/skills/, never something done from this page. */
async function Held() {
  await requireRole("ADMIN");
  let q: Quarantine;
  try {
    q = await call<Quarantine>("m6", "/quarantine");
  } catch (e) {
    if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
    throw e;
  }
  const bySkill = new Map<string, number>();
  for (const skills of Object.values(q.quarantined)) for (const s of skills) bySkill.set(s, (bySkill.get(s) ?? 0) + 1);
  const rows = [...bySkill].sort(([a], [b]) => a.localeCompare(b));
  return (
    <Card>
      <p className="mb-3 text-sm text-muted">
        Named in evidence, not on the skill list (ontology {q.ontology_version}). Each event still counts for the
        skills that are on it. To add one, extend <code>schemas/skills/</code> by a reviewed change.
      </p>
      {rows.length === 0 ? <p>Nothing held.</p> : (
        <ul className="space-y-1 text-sm">
          {rows.map(([skill, n]) => <li key={skill}><code>{skill}</code> <span className="text-muted">in {n} event(s)</span></li>)}
        </ul>
      )}
    </Card>
  );
}
