import { Suspense } from "react";

import { Conversation } from "@/components/conversation";
import { Loading, Page } from "@/components/ui";
import { requireCandidate } from "@/lib/candidate";

export default function ChatPage({ params }: PageProps<"/candidate/messages/[appId]">) {
  return (
    <Page title="Chat">
      <Suspense fallback={<Loading />}>
        <Chat params={params} />
      </Suspense>
    </Page>
  );
}

async function Chat({ params }: { params: Promise<{ appId: string }> }) {
  const user = await requireCandidate();
  return <Conversation user={user} appId={(await params).appId} />;
}
