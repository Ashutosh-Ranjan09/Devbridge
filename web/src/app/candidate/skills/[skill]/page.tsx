import { Suspense } from "react";

import { Interval } from "@/components/interval";
import { Card, Loading, Page } from "@/components/ui";
import { requireCandidate } from "@/lib/candidate";
import { call, ServiceError } from "@/lib/services";
import type { Explanation } from "@/lib/types";

const KIND: Record<string, string> = {
  assessment_result: "assessment result",
};

export default function SkillPage({ params }: PageProps<"/candidate/skills/[skill]">) {
  return (
    <Page title="How this range was reached">
      <Suspense fallback={<Loading />}>
        <Explained params={params} />
      </Suspense>
    </Page>
  );
}

async function Explained({ params }: { params: Promise<{ skill: string }> }) {
  const me = await requireCandidate();
  const { skill } = await params;
  let x: Explanation;
  try {
    x = await call<Explanation>(
      "m6",
      `/developers/${encodeURIComponent(me.subjectRef)}/skills/${encodeURIComponent(skill)}/explain`,
    );
  } catch (e) {
    if (e instanceof ServiceError) return <Card><p>{e.message}</p></Card>;
    throw e;
  }
  return (
    <Card>
      <h2 className="mb-2 font-semibold">{x.skill}</h2>
      <Interval interval={x.interval} mean={x.mean} />
      <p className="mt-2 text-sm text-muted">
        {x.evidence_count} piece(s) of evidence. Evidence counts for less as it ages (half-life {x.half_life_days} days).
      </p>
      <table className="mt-4 w-full text-left text-sm">
        <thead className="text-muted">
          <tr><th className="py-1">Evidence</th><th>Date</th><th>Observed</th><th>Weight</th><th>Mean after</th></tr>
        </thead>
        <tbody>
          {x.contributions.map((c) => (
            <tr key={c.event_id} className="border-t border-line">
              <td className="py-1">{KIND[c.kind] ?? c.kind.replaceAll("_", " ")}</td>
              <td>{c.occurred_at.slice(0, 10)}</td>
              <td className="font-mono">{c.observed.toFixed(2)}</td>
              <td className="font-mono">{c.weight.toFixed(2)}</td>
              <td className="font-mono">{c.moved_mean_to.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
