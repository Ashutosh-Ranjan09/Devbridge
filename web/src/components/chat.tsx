"use client";

import { type ReactNode, useActionState, useEffect, useRef, useState, useTransition } from "react";

import { type FormState, MAX_MESSAGE_CHARS } from "@/lib/definitions";
import { when } from "@/lib/tasks";
import type { ChatFile, ChatMessage, Seen, Side } from "@/lib/types";

import { Chip, Empty, Panel } from "./dashboard";
import { Icon } from "./icons";
import { Button } from "./ui";

type Act = (state: FormState, form: FormData) => Promise<FormState>;

/** What the chat module accepts; the bytes decide, this only narrows the file picker. */
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.docx";

/** One chat, live: messages arrive on the web's relay of the chat module's stream, the
 * sender's own included, so every open page shows the same thread in the same order.
 * Bodies are shown as text (whitespace kept), never as HTML or Markdown; files are links
 * that download, never shown in the page. */
export function ChatThread({ appId, me, side, header, about, initial, initialSeen, names, send, markRead, sendFile, requestDocument }: {
  appId: string;
  header: ReactNode; // who the chat is with, rendered on the server
  about: ReactNode; // the application it is about, beside the chat
  me: string;
  side: Side;
  initial: ChatMessage[];
  initialSeen: Seen;
  names: Record<string, string>;
  send: Act;
  markRead: (seq: number) => Promise<void>;
  sendFile: Act;
  requestDocument: Act | null; // a recruiter's; null for the candidate
}) {
  const [messages, setMessages] = useState(initial);
  const [seen, setSeen] = useState(initialSeen);
  const [live, setLive] = useState<"connecting" | "live" | "offline">("connecting");
  const newest = messages.at(-1)?.seq ?? 0;
  const latest = useRef(newest);
  useEffect(() => {
    latest.current = newest;
  }, [newest]);

  useEffect(() => {
    // Resumes after the newest message this page holds: when it was rendered, or when Next
    // shows a page it kept hidden (its effects are cleaned up while hidden, so the stream
    // closes). On a dropped connection the browser itself sends the last id it received.
    const source = new EventSource(`/api/chat/${encodeURIComponent(appId)}/stream?after=${latest.current}`);
    source.onopen = () => setLive("live");
    source.onerror = () => setLive(source.readyState === EventSource.CLOSED ? "offline" : "connecting");
    source.addEventListener("message", (e: MessageEvent<string>) => {
      const m = JSON.parse(e.data) as ChatMessage;
      setMessages((ms) => (ms.some((x) => x.seq === m.seq) ? ms : [...ms, m]));
    });
    source.addEventListener("seen", (e: MessageEvent<string>) => setSeen(JSON.parse(e.data) as Seen));
    return () => source.close();
  }, [appId]);

  // Seen once the page is in front of them, never from a tab in the background or a page
  // Next keeps hidden.
  const marked = useRef(0);
  const [, startTransition] = useTransition();
  useEffect(() => {
    const mark = () => {
      if (document.visibilityState !== "visible" || newest <= marked.current) return;
      marked.current = newest;
      // A server action called outside a form belongs in a transition (Next's guide);
      // called bare, its response broke the router and the page fell to the error screen.
      startTransition(async () => {
        await markRead(newest);
      });
    };
    mark();
    document.addEventListener("visibilitychange", mark);
    return () => document.removeEventListener("visibilitychange", mark);
  }, [newest, markRead]);

  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    // A block, not an expression: Chrome's scrollIntoView returns a promise now, and an
    // effect that returns one crashes React when it calls it as the clean-up.
    end.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  const [state, act, pending] = useActionState(send, undefined);
  const form = useRef<HTMLFormElement>(null);
  const other: Side = side === "candidate" ? "recruiter" : "candidate";
  const [tool, setTool] = useState<"attach" | "request" | null>(null);
  const who = (m: ChatMessage) =>
    m.sender === me ? "You" : (names[m.sender] ?? (m.side === "recruiter" ? "A recruiter" : "The candidate"));

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
      <section className="flex min-w-0 flex-col overflow-hidden rounded-2xl border border-line bg-panel">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
          {header}
          <div className="ml-auto flex items-center gap-3">
            <Chip><span className="inline-flex items-center gap-1"><Icon.Lock className="size-3" /> Encrypted</span></Chip>
            <span className="flex items-center gap-1.5 text-xs text-muted" aria-live="polite">
              <span className={`size-2 rounded-full ${live === "live" ? "bg-ok" : live === "connecting" ? "animate-pulse bg-highlight" : "bg-danger"}`} />
              <span>{live === "live" ? "Live" : live === "connecting" ? "Connecting…" : "Offline: reload to reconnect"}</span>
            </span>
          </div>
        </div>

        <ol className="flex h-[60vh] min-h-80 flex-col gap-4 overflow-y-auto bg-background/60 px-4 py-5 sm:px-6">
          {messages.length === 0 && (
            <li className="m-auto"><Empty icon="Mail" title="No messages yet" text="Say hello. Messages arrive live on both sides." /></li>
          )}
          {messages.map((m) => {
            const mine = m.side === side;
            const read = mine && seen[other] >= m.seq;
            return (
              <li key={m.seq} className={`flex max-w-[85%] flex-col sm:max-w-[75%] ${mine ? "items-end self-end" : "items-start self-start"}`}>
                <p className="mb-1 px-1 text-xs text-muted">
                  {who(m)} · {when(m.sent_at)}
                  {mine && <span className={read ? "text-accent" : ""} title={read ? "Seen" : "Sent"}> {read ? "✓✓" : "✓"}</span>}
                </p>
                {m.kind === "request" ? (
                  <RequestCard request={m} appId={appId} sendFile={sendFile} canAnswer={side === "candidate"}
                    answers={messages.filter((x) => x.kind === "file" && x.request_id === m.id)} />
                ) : (
                  <>
                    {m.body && (
                      <div className={`rounded-2xl px-4 py-2.5 ${mine ? "rounded-br-md bg-accent text-on-accent" : "rounded-bl-md bg-panel ring-1 ring-line"}`}>
                        <p className="whitespace-pre-wrap break-words">{m.body}</p>
                      </div>
                    )}
                    {m.file && <div className={m.body ? "mt-1.5" : ""}><FileTile appId={appId} file={m.file} /></div>}
                    {m.request_id && (
                      <p className="mt-1 px-1 text-xs text-muted">
                        For the request: {messages.find((x) => x.id === m.request_id)?.body ?? "a document"}
                      </p>
                    )}
                  </>
                )}
              </li>
            );
          })}
          <li ref={end} aria-hidden />
        </ol>

        <div className="border-t border-line p-4 sm:p-5">
          <form ref={form} action={act} className="flex items-end gap-2">
            <label className="flex-1">
              <span className="sr-only">Message</span>
              <textarea
                name="body" rows={2} maxLength={MAX_MESSAGE_CHARS} required
                key={state?.values?.body ?? ""} defaultValue={state?.values?.body}
                placeholder="Write a message. Enter sends; Shift+Enter for a new line."
                className="block w-full resize-none rounded-xl border border-line bg-background px-4 py-3 outline-none transition focus:border-accent focus:bg-panel"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    form.current?.requestSubmit();
                  }
                }}
              />
            </label>
            <button type="submit" disabled={pending}
              className="rounded-xl bg-accent px-5 py-3 font-semibold text-on-accent transition hover:brightness-110 disabled:opacity-60">
              {pending ? "Sending…" : "Send"}
            </button>
          </form>
          {state?.errors?.body?.map((e) => <p key={e} className="mt-2 text-sm text-danger">{e}</p>)}
          {state?.message && <p className="mt-2 text-sm text-danger">{state.message}</p>}
          <div className="mt-3 flex flex-wrap gap-1">
            <Tool on={tool === "attach"} onClick={() => setTool(tool === "attach" ? null : "attach")} icon={<Icon.Upload className="size-4" />}>
              Attach a file
            </Tool>
            {requestDocument && (
              <Tool on={tool === "request"} onClick={() => setTool(tool === "request" ? null : "request")} icon={<Icon.File className="size-4" />}>
                Request a document
              </Tool>
            )}
          </div>
          {tool === "attach" && <AttachForm sendFile={sendFile} />}
          {tool === "request" && requestDocument && <RequestForm requestDocument={requestDocument} />}
        </div>
      </section>

      <aside className="space-y-6 lg:sticky lg:top-20 lg:self-start">
        {about}
        <Documents messages={messages} appId={appId} side={side} />
      </aside>
    </div>
  );
}

function Tool({ on, onClick, icon, children }: { on: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-expanded={on}
      className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition ${on ? "bg-accent/10 text-accent" : "text-muted hover:bg-background hover:text-foreground"}`}>
      {icon}{children}
    </button>
  );
}

const TYPE: Record<string, string> = {
  "application/pdf": "PDF",
  "image/png": "PNG",
  "image/jpeg": "JPG",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
};

function size(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** A download, never an inline view: the web serves it as an attachment. */
function FileTile({ appId, file }: { appId: string; file: ChatFile }) {
  return (
    <a href={`/api/chat/${encodeURIComponent(appId)}/files/${file.id}`} download title={`Download ${file.name}`}
      className="flex max-w-xs items-center gap-3 rounded-xl bg-panel p-3 ring-1 ring-line transition hover:ring-accent">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent"><Icon.File className="size-4" /></span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium">{file.name}</span>
        <span className="block text-xs text-muted">{TYPE[file.mime] ?? file.mime} · {size(file.size)}</span>
      </span>
    </a>
  );
}

function Errors({ state, field }: { state: FormState; field?: string }) {
  return (
    <>
      {field && state?.errors?.[field]?.map((e) => <p key={e} className="mt-2 text-sm text-danger">{e}</p>)}
      {state?.message && <p className="mt-2 text-sm text-danger">{state.message}</p>}
    </>
  );
}

const FILE_INPUT = "block w-full text-sm text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-accent/10 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-accent hover:file:bg-accent/15";
const TEXT_INPUT = "w-full rounded-xl border border-line bg-background px-4 py-2.5 outline-none transition focus:border-accent focus:bg-panel";

/** A recruiter's request: what was asked, what has been shared for it, and for the
 * candidate a way to answer with a file. */
function RequestCard({ request, answers, canAnswer, appId, sendFile }: {
  request: ChatMessage; answers: ChatMessage[]; canAnswer: boolean; appId: string; sendFile: Act;
}) {
  const [state, act, pending] = useActionState(sendFile, undefined);
  return (
    <div className="w-80 max-w-full rounded-2xl bg-panel p-4 ring-1 ring-line">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-highlight/15 text-highlight"><Icon.File className="size-4" /></span>
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted">Document requested</p>
          <p className="font-medium whitespace-pre-wrap break-words">{request.body}</p>
        </div>
      </div>
      {answers.length ? (
        <ul className="mt-3 space-y-2">
          {answers.map((a) => a.file && (
            <li key={a.seq}>
              <p className="mb-1 flex items-center gap-1 text-xs font-medium text-ok"><Icon.Check className="size-3.5" /> Shared</p>
              <FileTile appId={appId} file={a.file} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 flex items-center gap-1.5 text-sm text-muted"><Icon.Clock className="size-4" /> Waiting for the candidate</p>
      )}
      {canAnswer && (
        <form action={act} className="mt-3 space-y-2 border-t border-line pt-3">
          <input type="hidden" name="request" value={request.id} />
          <input type="file" name="file" accept={ACCEPT} required aria-label={`File for: ${request.body}`} className={FILE_INPUT} />
          <Button pending={pending}>{answers.length ? "Upload another" : "Upload"}</Button>
        </form>
      )}
      <Errors state={state} field="file" />
    </div>
  );
}

/** Every request and file in the thread, live: what the recruiter is still waiting for,
 * and what has been shared, without scrolling back through the messages. */
function Documents({ messages, appId, side }: { messages: ChatMessage[]; appId: string; side: Side }) {
  const requests = messages.filter((m) => m.kind === "request");
  const files = messages.filter((m) => m.kind === "file" && m.file);
  return (
    <Panel title="Documents">
      {requests.length === 0 && files.length === 0 ? (
        <Empty icon="File" title="Nothing shared yet"
          text={side === "recruiter" ? "Ask for a document, or attach one, from the chat." : "Files you and the recruiter share appear here."} />
      ) : (
        <div className="space-y-4">
          {requests.length > 0 && (
            <ul className="space-y-2">
              {requests.map((r) => {
                const shared = files.some((f) => f.request_id === r.id);
                return (
                  <li key={r.seq} className="flex items-center justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate">{r.body}</span>
                    {shared ? <Chip tone="accent">Shared</Chip> : <Chip>Waiting</Chip>}
                  </li>
                );
              })}
            </ul>
          )}
          {files.length > 0 && (
            <ul className="space-y-2 border-t border-line pt-4 first:border-0 first:pt-0">
              {files.map((f) => f.file && <li key={f.seq}><FileTile appId={appId} file={f.file} /></li>)}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}

function AttachForm({ sendFile }: { sendFile: Act }) {
  const [state, act, pending] = useActionState(sendFile, undefined);
  return (
    <form action={act} className="mt-3 space-y-3 rounded-xl bg-background p-4">
      <input type="file" name="file" accept={ACCEPT} required aria-label="File" className={FILE_INPUT} />
      <input name="note" maxLength={MAX_MESSAGE_CHARS} placeholder="A note (optional)" aria-label="Note"
        key={state?.values?.note ?? ""} defaultValue={state?.values?.note} className={TEXT_INPUT} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted">PDF, PNG, JPG or Word (.docx), at most 10 MB. Encrypted where it is stored.</p>
        <Button pending={pending}>Send file</Button>
      </div>
      <Errors state={state} field="file" />
    </form>
  );
}

function RequestForm({ requestDocument }: { requestDocument: Act }) {
  const [state, act, pending] = useActionState(requestDocument, undefined);
  return (
    <form action={act} className="mt-3 rounded-xl bg-background p-4">
      <div className="flex flex-wrap items-center gap-2">
        <input name="what" maxLength={200} required placeholder="Which document? e.g. Degree certificate" aria-label="Which document"
          key={state?.values?.what ?? ""} defaultValue={state?.values?.what} className={`${TEXT_INPUT} flex-1`} />
        <Button pending={pending}>Request</Button>
      </div>
      <Errors state={state} field="what" />
    </form>
  );
}
