"use client";

import { useActionState, useEffect, useRef, useState, useTransition } from "react";

import { type FormState, MAX_MESSAGE_CHARS } from "@/lib/definitions";
import { when } from "@/lib/tasks";
import type { ChatFile, ChatMessage, Seen, Side } from "@/lib/types";

import { Button } from "./ui";

type Act = (state: FormState, form: FormData) => Promise<FormState>;

/** What the chat module accepts; the bytes decide, this only narrows the file picker. */
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.docx";

/** One chat, live: messages arrive on the web's relay of the chat module's stream, the
 * sender's own included, so every open page shows the same thread in the same order.
 * Bodies are shown as text (whitespace kept), never as HTML or Markdown; files are links
 * that download, never shown in the page. */
export function ChatThread({ appId, me, side, initial, initialSeen, names, send, markRead, sendFile, requestDocument }: {
  appId: string;
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

  return (
    <div>
      <p className="mb-2 text-xs text-muted" aria-live="polite">
        {live === "live" ? "Live" : live === "connecting" ? "Connecting…" : "Offline: reload the page to reconnect."}
      </p>
      <ol className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto rounded-md border border-line bg-background p-3">
        {messages.length === 0 && <li className="text-sm text-muted">No messages yet.</li>}
        {messages.map((m) => {
          const mine = m.side === side;
          const read = mine && seen[other] >= m.seq;
          return (
            <li key={m.seq} className={`max-w-[85%] rounded-lg px-3 py-2 ${mine ? "self-end bg-accent/10" : "self-start bg-panel"}`}>
              <p className="text-xs text-muted">
                {m.sender === me ? "You" : (names[m.sender] ?? (m.side === "recruiter" ? "A recruiter" : "The candidate"))}
                {" · "}{when(m.sent_at)}
                {mine && <span className={read ? "text-accent" : ""} title={read ? "Seen" : "Sent"}> {read ? "✓✓" : "✓"}</span>}
              </p>
              {m.kind === "request" ? (
                <RequestCard request={m} appId={appId} sendFile={sendFile} canAnswer={side === "candidate"}
                  answers={messages.filter((x) => x.kind === "file" && x.request_id === m.id)} />
              ) : (
                <>
                  {m.body && <p className="whitespace-pre-wrap break-words">{m.body}</p>}
                  {m.file && <FileLink appId={appId} file={m.file} />}
                  {m.request_id && (
                    <p className="text-xs text-muted">
                      for the request: {messages.find((x) => x.id === m.request_id)?.body ?? "a document"}
                    </p>
                  )}
                </>
              )}
            </li>
          );
        })}
        <li ref={end} aria-hidden />
      </ol>
      <form ref={form} action={act} className="mt-3 flex items-end gap-2">
        <label className="flex-1">
          <span className="sr-only">Message</span>
          <textarea
            name="body" rows={2} maxLength={MAX_MESSAGE_CHARS} required
            key={state?.values?.body ?? ""} defaultValue={state?.values?.body}
            placeholder="Write a message. Enter sends; Shift+Enter for a new line."
            className="w-full rounded-md border border-line bg-background px-3 py-2 outline-none focus:border-accent"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                form.current?.requestSubmit();
              }
            }}
          />
        </label>
        <Button pending={pending}>Send</Button>
      </form>
      {state?.errors?.body?.map((e) => <p key={e} className="mt-1 text-sm text-danger">{e}</p>)}
      {state?.message && <p className="mt-1 text-sm text-danger">{state.message}</p>}
      <div className="mt-3 space-y-2 text-sm">
        <details>
          <summary className="cursor-pointer text-accent">📎 Attach a file</summary>
          <AttachForm sendFile={sendFile} />
        </details>
        {requestDocument && (
          <details>
            <summary className="cursor-pointer text-accent">Request a document</summary>
            <RequestForm requestDocument={requestDocument} />
          </details>
        )}
      </div>
    </div>
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
function FileLink({ appId, file }: { appId: string; file: ChatFile }) {
  return (
    <p className="mt-1">
      <a href={`/api/chat/${encodeURIComponent(appId)}/files/${file.id}`} download
        className="break-all text-accent underline">📎 {file.name}</a>
      <span className="text-xs text-muted"> · {TYPE[file.mime] ?? file.mime} · {size(file.size)}</span>
    </p>
  );
}

function Errors({ state, field }: { state: FormState; field?: string }) {
  return (
    <>
      {field && state?.errors?.[field]?.map((e) => <p key={e} className="mt-1 text-sm text-danger">{e}</p>)}
      {state?.message && <p className="mt-1 text-sm text-danger">{state.message}</p>}
    </>
  );
}

/** A recruiter's request: what was asked, what has been shared for it, and for the
 * candidate a way to answer with a file. */
function RequestCard({ request, answers, canAnswer, appId, sendFile }: {
  request: ChatMessage; answers: ChatMessage[]; canAnswer: boolean; appId: string; sendFile: Act;
}) {
  const [state, act, pending] = useActionState(sendFile, undefined);
  return (
    <div className="mt-1 rounded-md border border-line bg-background px-3 py-2">
      <p><span className="font-medium">Requested:</span> <span className="whitespace-pre-wrap break-words">{request.body}</span></p>
      {answers.length ? (
        <ul className="mt-1">
          {answers.map((a) => a.file && (
            <li key={a.seq} className="text-sm"><span className="text-ok">Shared</span> <FileLink appId={appId} file={a.file} /></li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">Waiting for the candidate.</p>
      )}
      {canAnswer && (
        <form action={act} className="mt-2 flex flex-wrap items-center gap-2">
          <input type="hidden" name="request" value={request.id} />
          <input type="file" name="file" accept={ACCEPT} required aria-label={`File for: ${request.body}`} className="text-sm" />
          <Button pending={pending}>{answers.length ? "Upload another" : "Upload"}</Button>
        </form>
      )}
      <Errors state={state} field="file" />
    </div>
  );
}

function AttachForm({ sendFile }: { sendFile: Act }) {
  const [state, act, pending] = useActionState(sendFile, undefined);
  return (
    <form action={act} className="mt-2 space-y-2">
      <input type="file" name="file" accept={ACCEPT} required aria-label="File" className="block text-sm" />
      <input name="note" maxLength={MAX_MESSAGE_CHARS} placeholder="A note (optional)" aria-label="Note"
        key={state?.values?.note ?? ""} defaultValue={state?.values?.note}
        className="w-full rounded-md border border-line bg-background px-3 py-2 outline-none focus:border-accent" />
      <p className="text-xs text-muted">PDF, PNG, JPG or Word (.docx), at most 10 MB. Encrypted where it is stored.</p>
      <Button pending={pending}>Send file</Button>
      <Errors state={state} field="file" />
    </form>
  );
}

function RequestForm({ requestDocument }: { requestDocument: Act }) {
  const [state, act, pending] = useActionState(requestDocument, undefined);
  return (
    <form action={act} className="mt-2 flex flex-wrap items-start gap-2">
      <input name="what" maxLength={200} required placeholder="e.g. Degree certificate" aria-label="Which document"
        key={state?.values?.what ?? ""} defaultValue={state?.values?.what}
        className="flex-1 rounded-md border border-line bg-background px-3 py-2 outline-none focus:border-accent" />
      <Button pending={pending}>Request</Button>
      <div className="w-full"><Errors state={state} field="what" /></div>
    </form>
  );
}
