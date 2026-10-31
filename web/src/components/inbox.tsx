import Link from "next/link";

import { Card } from "@/components/ui";
import type { CurrentUser } from "@/lib/auth";
import { inboxFor, messagesPath } from "@/lib/chat";
import { ServiceError } from "@/lib/services";
import { when } from "@/lib/tasks";

/** This person's chats, newest first, with what is unread. */
export async function Inbox({ user }: { user: CurrentUser }) {
  let rows: Awaited<ReturnType<typeof inboxFor>>;
  try {
    rows = await inboxFor(user);
  } catch (e) {
    if (!(e instanceof ServiceError)) throw e;
    return <Card><p>{e.message}</p></Card>;
  }
  const candidate = user.role === "CANDIDATE";
  if (!rows.length) {
    return (
      <Card>
        <p className="text-sm text-muted">
          {candidate ? "No chats yet. A company's recruiters can start one about your application."
            : "No chats yet. Start one from an applicant's page."}
        </p>
      </Card>
    );
  }
  return (
    <Card>
      <ul className="divide-y divide-line">
        {rows.map((r) => (
          <li key={r.thread_id} className="flex items-baseline justify-between gap-3 py-2">
            <Link href={`${messagesPath(user)}/${r.thread_id}`} className="text-accent underline">
              {candidate ? `${r.app.job.org.name} · ${r.app.job.title}` : `${r.app.candidate.user.name} · ${r.app.job.title}`}
            </Link>
            <span className="text-sm text-muted">
              {r.unread > 0 && <span className="mr-2 rounded-full bg-accent px-2 text-on-accent">{r.unread} unread</span>}
              {r.last_at ? when(r.last_at) : "no messages yet"}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
