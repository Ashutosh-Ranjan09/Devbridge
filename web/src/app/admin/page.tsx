import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { requireRole } from "@/lib/auth";
import { db } from "@/lib/db";
import { health } from "@/lib/services";

export default function AdminHome() {
  return (
    <Page title="System">
      <Suspense fallback={<Loading />}>
        <Status />
      </Suspense>
    </Page>
  );
}

async function Status() {
  await requireRole("ADMIN");
  const [services, roles, jobs, open, applications, decided, verifications, assessments, pending] = await Promise.all([
    health(),
    db.user.groupBy({ by: ["role"], _count: { _all: true } }),
    db.job.count(),
    db.job.count({ where: { open: true } }),
    db.application.count(),
    db.decision.count(),
    db.verification.count(),
    db.assessment.count(),
    Promise.all([
      db.verification.count({ where: { sentToM6At: null } }),
      db.assessment.count({ where: { sentToM6At: null } }),
    ]),
  ]);
  const counts: [string, number][] = [
    ...roles.map((r) => [`${r.role.toLowerCase()} accounts`, r._count._all] as [string, number]),
    ["jobs", jobs], ["open for applications", open], ["applications", applications], ["decided", decided],
    ["CVs checked", verifications], ["assessments issued", assessments],
    ["not yet accepted by M6", pending[0] + pending[1]],
  ];
  return (
    <div className="space-y-4">
      <Card>
        <h2 className="mb-3 font-semibold">Modules</h2>
        <ul className="space-y-2">
          {services.map((s) => (
            <li key={s.service} className="flex flex-wrap items-baseline gap-x-3">
              <span className={s.ok ? "text-ok" : "text-danger"}>{s.ok ? "●" : "○"}</span>
              <span className="font-medium">{s.label}</span>
              <code className="text-sm text-muted">{s.url}</code>
              <span className="text-sm">{s.detail}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <h2 className="mb-3 font-semibold">This site</h2>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          {counts.map(([label, n]) => (
            <div key={label} className="contents"><dt className="text-muted">{label}</dt><dd className="font-mono">{n}</dd></div>
          ))}
        </dl>
        <p className="mt-3 text-xs text-muted">Counts of activity on this site. Nothing here describes any person.</p>
      </Card>
    </div>
  );
}
