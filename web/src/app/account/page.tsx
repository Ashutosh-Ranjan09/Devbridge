import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { requireUser } from "@/lib/auth";
import { db } from "@/lib/db";

import { ChangePasswordForm } from "./form";

export default function AccountPage() {
  return (
    <Page title="Your account">
      <Suspense fallback={<Loading />}>
        <Account />
      </Suspense>
    </Page>
  );
}

async function Account() {
  const me = await requireUser();
  const extra = await db.user.findUniqueOrThrow({
    where: { id: me.id },
    select: {
      createdAt: true,
      candidate: { select: { subjectRef: true } },
      memberships: { select: { org: { select: { name: true } } } },
    },
  });
  return (
    <div className="space-y-4">
      <Card>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-muted">Name</dt><dd>{me.name}</dd>
          <dt className="text-muted">Email</dt><dd className="break-all">{me.email}</dd>
          <dt className="text-muted">Role</dt><dd>{me.role.toLowerCase()}</dd>
          {extra.candidate && (
            <><dt className="text-muted">Known to the modules as</dt><dd><code className="break-all">{extra.candidate.subjectRef}</code></dd></>
          )}
          {extra.memberships.length > 0 && (
            <><dt className="text-muted">Hiring for</dt><dd>{extra.memberships.map((m) => m.org.name).join(", ")}</dd></>
          )}
          <dt className="text-muted">Joined</dt><dd>{extra.createdAt.toLocaleDateString("en-IN")}</dd>
        </dl>
      </Card>
      <Card>
        <h2 className="mb-3 font-semibold">Change password</h2>
        <ChangePasswordForm />
      </Card>
    </div>
  );
}
