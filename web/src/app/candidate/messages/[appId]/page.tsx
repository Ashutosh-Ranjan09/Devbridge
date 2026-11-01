import Link from "next/link";
import { Suspense } from "react";

import { Conversation } from "@/components/conversation";
import { Icon } from "@/components/icons";
import { requireCandidate } from "@/lib/candidate";

export default function ChatPage({ params }: PageProps<"/candidate/messages/[appId]">) {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
      <Link href="/candidate/messages" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline">
        <Icon.Chevron className="size-4 rotate-90" /> All messages
      </Link>
      <Suspense fallback={<div className="h-[70vh] animate-pulse rounded-2xl bg-line" />}>
        <Chat params={params} />
      </Suspense>
    </main>
  );
}

async function Chat({ params }: { params: Promise<{ appId: string }> }) {
  const user = await requireCandidate();
  return <Conversation user={user} appId={(await params).appId} />;
}
