import { currentUser } from "@/lib/auth";
import { threadFor } from "@/lib/chat";
import { ServiceError, stream } from "@/lib/services";

/** A file shared in a chat, for the people on it; anyone else gets the same 404 as a file
 * that does not exist. Always a download, never shown in the page: the type is the one the
 * chat module sniffed from the bytes, the browser is told not to guess another, and a
 * sandbox policy stops anything in it running even if it were opened here. */
export async function GET(request: Request, ctx: RouteContext<"/api/chat/[appId]/files/[fileId]">) {
  const user = await currentUser();
  const { appId, fileId } = await ctx.params;
  const app = user && (await threadFor(user, appId));
  if (!app || !/^file_[0-9a-f]{16}$/.test(fileId)) return new Response("Not found", { status: 404 });
  let upstream: Response;
  try {
    upstream = await stream("chat", `/v1/threads/${encodeURIComponent(app.id)}/files/${fileId}`, request.signal, "*/*");
  } catch (e) {
    if (!(e instanceof ServiceError)) throw e;
    return new Response(e.status === 404 ? "Not found" : "The chat is not answering", { status: e.status === 404 ? 404 : 503 });
  }
  const name = decodeURIComponent(upstream.headers.get("x-file-name") ?? "file");
  return new Response(upstream.body, {
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/octet-stream",
      "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(name)}`,
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "sandbox; default-src 'none'",
      "Cache-Control": "private, no-store",
    },
  });
}
