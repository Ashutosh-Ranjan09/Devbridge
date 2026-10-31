import type { NextRequest } from "next/server";

import { mayReadFilesOf } from "@/lib/access";
import { currentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { fileResponse, readStored } from "@/lib/files";

/** A document a candidate uploaded beside their CV, to whoever may read their files. */
export async function GET(_req: NextRequest, ctx: RouteContext<"/files/proof/[id]">) {
  const { id } = await ctx.params;
  const user = await currentUser();
  const proof = await db.proof.findUnique({ where: { id }, include: { verification: { select: { candidateId: true } } } });
  if (!user || !proof || !(await mayReadFilesOf(user, proof.verification.candidateId))) {
    return new Response("Not found", { status: 404 });
  }
  const bytes = await readStored("proofs", proof.id, proof.fileName);
  return bytes ? fileResponse(bytes, proof.fileName) : new Response("Not found", { status: 404 });
}
