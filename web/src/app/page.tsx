import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { Card, Loading, Page } from "@/components/ui";
import { currentUser, HOME } from "@/lib/auth";

export default function Home() {
  return (
    <Page title="DevBridge">
      <Suspense fallback={<Loading />}>
        <Welcome />
      </Suspense>
    </Page>
  );
}

async function Welcome() {
  const user = await currentUser();
  if (user) redirect(HOME[user.role]);
  return (
    <Card>
      <p className="mb-4">
        A developer&apos;s CV checked against the systems it names, skills measured from that
        evidence, and coding tasks that are unique to each candidate and equally hard. No
        overall score: a person reads the evidence and decides.
      </p>
      <div className="flex gap-4">
        <Link href="/signup" className="rounded-md bg-accent px-4 py-2 font-medium text-on-accent">
          Create an account
        </Link>
        <Link href="/login" className="px-4 py-2 text-accent underline">Log in</Link>
      </div>
    </Card>
  );
}
