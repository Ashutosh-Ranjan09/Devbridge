import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";

import { ResetForm } from "./form";

/** Opened from an admin's one-time link, signed out. Whether the link is still good is
 * decided when the form is sent, so this page says nothing about a token. */
export default function ResetPage({ params }: PageProps<"/reset/[token]">) {
  return (
    <Page title="Choose a new password">
      <Card>
        <Suspense fallback={<Loading />}>
          <Reset params={params} />
        </Suspense>
      </Card>
    </Page>
  );
}

async function Reset({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <ResetForm token={token} />;
}
