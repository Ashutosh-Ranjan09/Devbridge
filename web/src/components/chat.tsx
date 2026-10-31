"use client";

import { useActionState, useEffect, useRef, useState, useTransition } from "react";

import { type FormState, MAX_MESSAGE_CHARS } from "@/lib/definitions";
import { when } from "@/lib/tasks";
import type { ChatMessage, Seen, Side } from "@/lib/types";

import { Button } from "./ui";

/** One chat, live: messages arrive on the web's relay of the chat module's stream, the
 * sender's own included, so every open page shows the same thread in the same order.
 * Bodies are shown as text (whitespace kept), never as HTML or Markdown. */
export function ChatThread({ appId, me, side, initial, initialSeen, names, send, markRead }: {
  appId: string;
  me: string;
  side: Side;
  initial: ChatMessage[];
  initialSeen: Seen;
  names: Record<string, string>;
  send: (state: FormState, form: FormData) => Promise<FormState>;
  markRead: (seq: number) => Promise<void>;
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
              <p className="whitespace-pre-wrap break-words">{m.body}</p>
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
    </div>
  );
}
