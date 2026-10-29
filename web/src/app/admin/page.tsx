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
  const [services, roles] = await Promise.all([
    health(),
    db.user.groupBy({ by: ["role"], _count: { _all: true } }),
  ]);
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
        <h2 className="mb-3 font-semibold">Accounts</h2>
        <ul>
          {roles.map((r) => <li key={r.role}>{r.role.toLowerCase()}: {r._count._all}</li>)}
        </ul>
      </Card>
    </div>
  );
}
