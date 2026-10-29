import Link from "next/link";

import { Card, Page } from "@/components/ui";

/** One page for "does not exist" and "is not yours": the same answer for both, so an id
 * cannot be probed for whether it exists. */
export default function NotFound() {
  return (
    <Page title="Not found">
      <Card>
        <p>This page could not be found.</p>
        <p className="mt-1 text-sm text-muted">It does not exist, or it belongs to someone else.</p>
        <Link href="/" className="mt-4 inline-block text-accent underline">Go to your home page</Link>
      </Card>
    </Page>
  );
}
