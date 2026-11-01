import Link from "next/link";

import { Chip, Empty, OrgBadge, Panel } from "@/components/dashboard";
import type { CurrentUser } from "@/lib/auth";
import { inboxFor, messagesPath } from "@/lib/chat";
import { ServiceError } from "@/lib/services";
import { when } from "@/lib/tasks";

/** This person's chats, newest first, with what is unread: a company for a developer, a
 * candidate for a recruiter. */
export async function Inbox({ user }: { user: CurrentUser }) {
  let rows: Awaited<ReturnType<typeof inboxFor>>;
  try {
    rows = await inboxFor(user);
  } catch (e) {
    if (!(e instanceof ServiceError)) throw e;
    return <Panel title="Conversations"><p className="text-muted">{e.message}</p></Panel>;
  }
  const candidate = user.role === "CANDIDATE";
  return (
    <Panel title={`Conversations${rows.length ? ` (${rows.length})` : ""}`}>
      {rows.length === 0 ? (
        <Empty icon="Mail" title="No conversations yet"
          text={candidate ? "When a company's recruiter starts a chat about one of your applications, it appears here."
            : "Start a chat from an applicant's page; it appears here."} />
      ) : (
        <ul className="-mx-2 divide-y divide-line">
          {rows.map((r) => {
            const name = candidate ? r.app.job.org.name : r.app.candidate.user.name;
            return (
              <li key={r.thread_id}>
                <Link href={`${messagesPath(user)}/${r.thread_id}`}
                  className="flex items-center gap-4 rounded-xl px-2 py-3.5 transition hover:bg-background">
                  <OrgBadge name={name} />
                  <div className="min-w-0 flex-1">
                    <p className={`truncate ${r.unread ? "font-semibold" : "font-medium"}`}>{name}</p>
                    <p className="truncate text-sm text-muted">{r.app.job.title}</p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    <span className="text-xs text-muted">{r.last_at ? when(r.last_at) : "No messages yet"}</span>
                    {r.unread > 0 && <Chip tone="accent">{r.unread} unread</Chip>}
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
