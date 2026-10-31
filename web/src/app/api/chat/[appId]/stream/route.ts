import { currentUser } from "@/lib/auth";
import { threadFor } from "@/lib/chat";
import { ServiceError, stream } from "@/lib/services";

/** A chat's live messages and read marks, relayed from the chat module: the browser never
 * reaches a module. Someone not on the thread gets the same 404 as a thread that does not
 * exist. The browser's EventSource reconnects by itself, sending the last id it had, so
 * nothing is lost across a dropped connection. */
export async function GET(request: Request, ctx: RouteContext<"/api/chat/[appId]/stream">) {
  const user = await currentUser();
  const app = user && (await threadFor(user, (await ctx.params).appId));
  if (!app) return new Response("Not found", { status: 404 });
  const last = request.headers.get("last-event-id") ?? new URL(request.url).searchParams.get("after") ?? "0";
  const after = /^\d{1,15}$/.test(last) ? last : "0";
  try {
    const upstream = await stream("chat", `/v1/threads/${encodeURIComponent(app.id)}/events?after=${after}`, request.signal);
    return new Response(upstream.body, {
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no" },
    });
  } catch (e) {
    if (!(e instanceof ServiceError)) throw e;
    // 204 tells EventSource to stop retrying: a thread nobody opened will not open by waiting.
    return new Response(null, { status: e.status === 404 ? 204 : 503 });
  }
}
