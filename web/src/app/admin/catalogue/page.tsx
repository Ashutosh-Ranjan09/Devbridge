import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { requireRole } from "@/lib/auth";
import { call, ServiceError } from "@/lib/services";
import type { Pattern, Rule } from "@/lib/types";

export default function CataloguePage() {
  return (
    <Page title="Checks and tasks">
      <Suspense fallback={<Loading />}>
        <Catalogue />
      </Suspense>
    </Page>
  );
}

const TIER: Record<Rule["tier"], string> = {
  decisive: "decisive: an authoritative source, compared exactly",
  attention: "attention: a signal with innocent explanations",
  evidence_only: "evidence only: material for a person",
};

async function Catalogue() {
  await requireRole("ADMIN");
  const [rules, patterns] = await Promise.all([
    call<Rule[]>("m5", "/v1/rules").catch((e: unknown) => (e instanceof ServiceError ? e : Promise.reject(e))),
    call<Pattern[]>("assess", "/v1/patterns").catch((e: unknown) => (e instanceof ServiceError ? e : Promise.reject(e))),
  ]);
  return (
    <div className="space-y-4">
      <Card>
        <h2 className="mb-1 font-semibold">CV checks (M5)</h2>
        {rules instanceof ServiceError ? <p>{rules.message}</p> : (
          <>
            <p className="mb-3 text-sm text-muted">
              {rules.length} checks. A check that does not score is shown to a person and moves no number.
            </p>
            {(Object.keys(TIER) as Rule["tier"][]).map((tier) => (
              <div key={tier} className="mb-3">
                <h3 className="text-sm font-medium">{TIER[tier]}</h3>
                <ul className="mt-1 space-y-1 text-sm">
                  {rules.filter((r) => r.tier === tier).map((r) => (
                    <li key={r.rule_id}>
                      <code className="text-muted">{r.rule_id}</code> {r.summary}
                      {!r.scoring && <span className="text-xs text-muted"> · does not score</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </>
        )}
      </Card>
      <Card>
        <h2 className="mb-1 font-semibold">Assessment tasks</h2>
        {patterns instanceof ServiceError ? <p>{patterns.message}</p> : (
          <>
            <p className="mb-3 text-sm text-muted">
              Each is used only after its hidden tests are proven right in every combination, and every
              variant of one is equally hard.
            </p>
            <ul className="space-y-2 text-sm">
              {patterns.map((p) => (
                <li key={p.id}>
                  <span className="font-medium">{p.title}</span>{" "}
                  <span className="text-muted">
                    · <code>{p.id}</code> · tests <code>{p.skill}</code> · {p.level} · {p.time_limit_minutes} min · {p.variants} variants
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </div>
  );
}
