import { Suspense } from "react";

import { Inbox } from "@/components/inbox";
import { requireCandidate } from "@/lib/candidate";

export default function MessagesPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Messages</h1>
        <p className="mt-1 max-w-2xl text-muted">Talk to companies about your applications. A recruiter starts each chat; you reply, and share the documents they ask for.</p>
      </div>
      <Suspense fallback={<div className="h-64 animate-pulse rounded-2xl bg-line" />}>
        <Mine />
      </Suspense>
    </main>
  );
}

async function Mine() {
  return <Inbox user={await requireCandidate()} />;
}
