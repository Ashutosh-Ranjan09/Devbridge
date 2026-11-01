import type { NextRequest } from "next/server";

import { mayReadFilesOf } from "@/lib/access";
import { currentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { fileResponse, readStored } from "@/lib/files";

/** A candidate's uploaded CV, to whoever may read their files (lib/access.ts). */
export async function GET(_req: NextRequest, ctx: RouteContext<"/files/cv/[id]">) {
  const { id } = await ctx.params;
  const user = await currentUser();
  const cv = await db.verification.findUnique({ where: { id } });
  if (!user || !cv || !(await mayReadFilesOf(user, cv.candidateId))) return new Response("Not found", { status: 404 });
  const bytes = await readStored("cv", cv.id, cv.fileName);
  return bytes ? fileResponse(bytes, cv.fileName) : new Response("Not found", { status: 404 });
}
