"use server";

import { notFound } from "next/navigation";
import * as z from "zod";

import { requireUser } from "@/lib/auth";
import { sideOf, threadFor } from "@/lib/chat";
import { FileSchema, type FormState, MessageSchema, RequestSchema, typed } from "@/lib/definitions";
import { call, ServiceError } from "@/lib/services";

/** Both sides of a chat. Each action finds the application through the person sending
 * (`threadFor`): another candidate's thread, another company's, or an admin, is a 404.
 * Only user ids reach the chat module. Opening a thread is the recruiter's, in
 * recruiter/actions.ts; nothing here can. */

export async function sendMessage(appId: string, _: FormState, form: FormData): Promise<FormState> {
  const me = await requireUser();
  const app = (await threadFor(me, appId)) ?? notFound();
  const parsed = MessageSchema.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: typed(form) };
  try {
    await call("chat", `/v1/threads/${encodeURIComponent(app.id)}/messages`, {
      body: { sender: me.id, side: sideOf(me), body: parsed.data.body },
    });
  } catch (e) {
    if (!(e instanceof ServiceError)) throw e;
    const message = e.status === 404 ? "The recruiter has not started a chat for this application."
      : e.status === 429 ? "Too many messages in a minute; wait a moment." : e.message;
    return { message, values: typed(form) };
  }
  return undefined; // the message comes back on the stream, to every open page alike
}

/** A recruiter asks for a document; it shows in the thread as a card the candidate can
 * answer with a file. A candidate cannot ask: the action is a 404 to them. */
export async function requestDocument(appId: string, _: FormState, form: FormData): Promise<FormState> {
  const me = await requireUser();
  const app = (me.role === "RECRUITER" ? await threadFor(me, appId) : null) ?? notFound();
  const parsed = RequestSchema.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: typed(form) };
  try {
    await call("chat", `/v1/threads/${encodeURIComponent(app.id)}/messages`, {
      body: { sender: me.id, side: "recruiter", kind: "request", body: parsed.data.what },
    });
  } catch (e) {
    if (e instanceof ServiceError) return { message: e.message, values: typed(form) };
    throw e;
  }
  return undefined;
}

/** A file, with an optional note, perhaps answering a request (`request`, its message id).
 * Either side may share one. Its type is decided by the chat module from the bytes. */
export async function sendFile(appId: string, _: FormState, form: FormData): Promise<FormState> {
  const me = await requireUser();
  const app = (await threadFor(me, appId)) ?? notFound();
  const parsed = FileSchema.safeParse({ file: form.get("file"), note: form.get("note") ?? "", request: form.get("request") ?? "" });
  if (!parsed.success) return { errors: z.flattenError(parsed.error).fieldErrors, values: typed(form) };
  const { file, note, request } = parsed.data;
  const upload = new FormData();
  upload.set("sender", me.id);
  upload.set("side", sideOf(me));
  upload.set("note", note);
  if (request) upload.set("request_id", request);
  upload.set("file", file, file.name);
  try {
    await call("chat", `/v1/threads/${encodeURIComponent(app.id)}/files`, { form: upload, timeoutMs: 60_000 });
  } catch (e) {
    if (e instanceof ServiceError) return { message: e.message, values: typed(form) };
    throw e;
  }
  return undefined;
}

/** The newest message this person has seen. The chat module keeps a mark moving forward
 * only, so an old tab cannot unread anything. */
export async function markRead(appId: string, seq: number): Promise<void> {
  const me = await requireUser();
  const app = (await threadFor(me, appId)) ?? notFound();
  if (!Number.isSafeInteger(seq) || seq < 0) return;
  await call("chat", `/v1/threads/${encodeURIComponent(app.id)}/read`, {
    body: { reader: me.id, side: sideOf(me), seq },
  }).catch((e: unknown) => {
    if (!(e instanceof ServiceError)) throw e; // a mark that misses is the next one's job
  });
}
