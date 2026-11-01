import { notFound } from "next/navigation";

import { markRead, requestDocument, sendFile, sendMessage } from "@/app/chat/actions";
import { startChat } from "@/app/recruiter/actions";
import { ActionButton } from "@/components/action-button";
import { ChatThread } from "@/components/chat";
import { Chip, Empty, LinkButton, OrgBadge, Panel, STAGE_NOW, Stages } from "@/components/dashboard";
import { Icon } from "@/components/icons";
import type { CurrentUser } from "@/lib/auth";
import { type ChatApplication, namesOn, sideOf, threadFor, threadView } from "@/lib/chat";
import { ServiceError } from "@/lib/services";
import { day } from "@/lib/tasks";
import type { ThreadView } from "@/lib/types";

/** One application's chat, for either side. Not on it: 404. Not opened yet: the recruiter
 * can open it here; the candidate is told only a recruiter can. */
export async function Conversation({ user, appId }: { user: CurrentUser; appId: string }) {
  const app = (await threadFor(user, appId)) ?? notFound();
  const candidate = user.role === "CANDIDATE";
  const name = candidate ? app.job.org.name : app.candidate.user.name;
  let view: ThreadView | null;
  try {
    view = await threadView(app.id);
  } catch (e) {
    if (!(e instanceof ServiceError)) throw e;
    return <Panel title="Chat"><p className="text-muted">{e.message}</p></Panel>;
  }
  const header = (
    <div className="flex min-w-0 items-center gap-3">
      <OrgBadge name={name} />
      <div className="min-w-0">
        <h1 className="truncate font-semibold">{name}</h1>
        <p className="truncate text-sm text-muted">{candidate ? app.job.title : `Applied to ${app.job.title}`}</p>
      </div>
    </div>
  );
  const about = <About app={app} candidate={candidate} />;

  if (!view) {
    return (
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
        <section className="rounded-2xl border border-line bg-panel">
          <div className="border-b border-line px-5 py-4">{header}</div>
          <Empty icon="Mail" title="No chat yet"
            text={candidate ? "Only the company's recruiters can start one; you can reply once they do."
              : "Start it and the candidate can reply. Only a recruiter can start a chat."}
            action={candidate ? undefined : <ActionButton action={startChat.bind(null, app.jobId, app.id)} label="Start chat" />} />
        </section>
        <aside className="lg:sticky lg:top-20 lg:self-start">{about}</aside>
      </div>
    );
  }
  return (
    <ChatThread
      appId={app.id} me={user.id} side={sideOf(user)} header={header} about={about}
      initial={view.messages} initialSeen={view.seen} names={namesOn(app)}
      send={sendMessage.bind(null, app.id)} markRead={markRead.bind(null, app.id)}
      sendFile={sendFile.bind(null, app.id)}
      requestDocument={candidate ? null : requestDocument.bind(null, app.id)}
    />
  );
}

/** The application the chat is about: who and which job, and where it has got to. */
function About({ app, candidate }: { app: ChatApplication; candidate: boolean }) {
  const other = candidate ? app.job.org.name : app.candidate.user.name;
  return (
    <Panel title="About this application">
      <div className="flex items-start gap-3">
        <OrgBadge name={other} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{app.job.title}</p>
          <p className="text-xs text-muted">{other} · applied {day(app.createdAt)}</p>
        </div>
      </div>
      <div className="mt-3"><Chip>{STAGE_NOW[app.status]}</Chip></div>
      <Stages status={app.status} />
      {!candidate && (
        <div className="mt-5"><LinkButton href={`/recruiter/jobs/${app.jobId}/applicants/${app.id}`}>Open applicant</LinkButton></div>
      )}
      <p className="mt-5 flex items-start gap-2 text-xs text-muted">
        <Icon.Lock className="mt-px size-3.5 shrink-0" />
        Encrypted where it is stored. {candidate ? "You and the company's recruiters" : "The candidate and your company's recruiters"} can read it.
      </p>
    </Panel>
  );
}
