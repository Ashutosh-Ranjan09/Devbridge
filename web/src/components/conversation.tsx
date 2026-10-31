import Link from "next/link";
import { notFound } from "next/navigation";

import { markRead, requestDocument, sendFile, sendMessage } from "@/app/chat/actions";
import { startChat } from "@/app/recruiter/actions";
import { ActionButton } from "@/components/action-button";
import { ChatThread } from "@/components/chat";
import { Card } from "@/components/ui";
import type { CurrentUser } from "@/lib/auth";
import { namesOn, sideOf, threadFor, threadView } from "@/lib/chat";
import { ServiceError } from "@/lib/services";
import type { ThreadView } from "@/lib/types";

/** One application's chat, for either side. Not on it: 404. Not opened yet: the recruiter
 * can open it here; the candidate is told only a recruiter can. */
export async function Conversation({ user, appId }: { user: CurrentUser; appId: string }) {
  const app = (await threadFor(user, appId)) ?? notFound();
  const candidate = user.role === "CANDIDATE";
  let view: ThreadView | null;
  try {
    view = await threadView(app.id);
  } catch (e) {
    if (!(e instanceof ServiceError)) throw e;
    return <Card><p>{e.message}</p></Card>;
  }
  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-xl font-semibold">{candidate ? app.job.org.name : app.candidate.user.name}</h2>
        <p className="text-sm text-muted">
          {candidate ? app.job.title : (
            <>applied to <Link href={`/recruiter/jobs/${app.jobId}/applicants/${app.id}`} className="underline">{app.job.title}</Link></>
          )}
          {" · "}encrypted where it is stored; {candidate ? "you and the company's recruiters" : "the candidate and your company's recruiters"} can read it
        </p>
      </div>
      <Card>
        {view ? (
          <ChatThread
            appId={app.id} me={user.id} side={sideOf(user)}
            initial={view.messages} initialSeen={view.seen} names={namesOn(app)}
            send={sendMessage.bind(null, app.id)} markRead={markRead.bind(null, app.id)}
            sendFile={sendFile.bind(null, app.id)}
            requestDocument={candidate ? null : requestDocument.bind(null, app.id)}
          />
        ) : candidate ? (
          <p className="text-sm text-muted">No chat yet. Only the company&apos;s recruiters can start one; you can reply once they do.</p>
        ) : (
          <ActionButton action={startChat.bind(null, app.jobId, app.id)} label="Start chat"
            note="The candidate can reply once you start it." />
        )}
      </Card>
    </div>
  );
}
