import { Suspense } from "react";

import { Conversation } from "@/components/conversation";
import { Loading, Page } from "@/components/ui";
import { requireRecruiter } from "@/lib/recruiter";

export default function ChatPage({ params }: PageProps<"/recruiter/messages/[appId]">) {
  return (
    <Page title="Chat">
      <Suspense fallback={<Loading />}>
        <Chat params={params} />
      </Suspense>
    </Page>
  );
}

async function Chat({ params }: { params: Promise<{ appId: string }> }) {
  const user = await requireRecruiter();
  return <Conversation user={user} appId={(await params).appId} />;
}
