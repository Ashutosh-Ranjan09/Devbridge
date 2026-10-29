import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { requireRole } from "@/lib/auth";
import { db } from "@/lib/db";

export default function AccountsPage() {
  return (
    <Page title="Accounts">
      <Suspense fallback={<Loading />}>
        <Accounts />
      </Suspense>
    </Page>
  );
}

async function Accounts() {
  await requireRole("ADMIN");
  const users = await db.user.findMany({
    orderBy: [{ role: "asc" }, { name: "asc" }],
    select: {
      id: true, name: true, email: true, role: true, createdAt: true,
      candidate: { select: { subjectRef: true } },
      memberships: { select: { org: { select: { name: true } } } },
    },
  });
  return (
    <Card>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-muted">
            <tr><th className="py-1 pr-3">Name</th><th className="pr-3">Email</th><th className="pr-3">Role</th><th className="pr-3">Known to the modules as / hiring for</th><th>Joined</th></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-t border-line">
                <td className="py-1 pr-3">{u.name}</td>
                <td className="pr-3">{u.email}</td>
                <td className="pr-3">{u.role.toLowerCase()}</td>
                <td className="pr-3">
                  {u.candidate ? <code>{u.candidate.subjectRef}</code> : u.memberships.map((m) => m.org.name).join(", ")}
                </td>
                <td className="whitespace-nowrap">{u.createdAt.toLocaleDateString("en-IN")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-muted">Admins are made with <code>npm run create-admin</code>, never by signing up.</p>
    </Card>
  );
}
