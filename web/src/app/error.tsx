"use client";

import { Card, Page } from "@/components/ui";

/** An unexpected failure: a module refused in a way no page handles, or a bug. A server
 * error arrives with its message hidden and a digest that matches the server's log. */
export default function ErrorPage({ error, retry }: { error: unknown; retry: () => void }) {
  const digest = error instanceof Error && "digest" in error ? String(error.digest) : null;
  return (
    <Page title="Something went wrong">
      <Card>
        <p>The page could not be shown. Nothing you entered was lost on our side.</p>
        {digest && <p className="mt-1 text-sm text-muted">Reference <code>{digest}</code> (in the server&apos;s log).</p>}
        <button type="button" onClick={() => retry()} className="mt-4 rounded-md bg-accent px-4 py-2 font-medium text-on-accent">
          Try again
        </button>
      </Card>
    </Page>
  );
}
