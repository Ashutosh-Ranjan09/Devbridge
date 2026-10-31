import { Suspense } from "react";

import { Inbox } from "@/components/inbox";
import { Loading, Page } from "@/components/ui";
import { requireCandidate } from "@/lib/candidate";

export default function MessagesPage() {
  return (
    <Page title="Messages">
      <Suspense fallback={<Loading />}>
        <Mine />
      </Suspense>
    </Page>
  );
}

async function Mine() {
  return <Inbox user={await requireCandidate()} />;
}
