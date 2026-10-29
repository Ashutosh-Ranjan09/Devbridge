import Link from "next/link";
import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { requireRole } from "@/lib/auth";
import { db } from "@/lib/db";

export default function CandidatesPage() {
  return (
    <Page title="Candidates">
      <Suspense fallback={<Loading />}>
        <Candidates />
      </Suspense>
    </Page>
  );
}

/** Every candidate, by name: an admin checks their CV reports line by line from here. */
async function Candidates() {
  await requireRole("ADMIN");
  const people = await db.candidate.findMany({
    orderBy: { user: { name: "asc" } },
    select: {
      userId: true, subjectRef: true,
      user: { select: { name: true, email: true } },
      verifications: { select: { _count: { select: { reviews: true } } } },
    },
  });
  if (!people.length) return <Card><p>No candidates yet.</p></Card>;
  return (
    <Card>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-muted">
            <tr><th className="py-1 pr-3">Name</th><th className="pr-3">Email</th><th className="pr-3">Known to the modules as</th><th className="pr-3">CVs</th><th>Marks</th></tr>
          </thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.userId} className="border-t border-line">
                <td className="py-1 pr-3">
                  <Link href={`/admin/candidates/${p.userId}`} className="text-accent hover:underline">{p.user.name}</Link>
                </td>
                <td className="pr-3">{p.user.email}</td>
                <td className="pr-3"><code>{p.subjectRef}</code></td>
                <td className="pr-3 font-mono">{p.verifications.length}</td>
                <td className="font-mono">{p.verifications.reduce((n, v) => n + v._count.reviews, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-muted">Marks counts every mark made, including ones later changed.</p>
    </Card>
  );
}
