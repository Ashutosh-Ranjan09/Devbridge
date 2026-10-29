import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";

import type { Role } from "@/generated/prisma/enums";

import { db } from "./db";
import { sessionUserId } from "./session";

export type CurrentUser = { id: string; name: string; email: string; role: Role };

export const HOME: Record<Role, string> = {
  CANDIDATE: "/candidate",
  RECRUITER: "/recruiter",
  ADMIN: "/admin",
};

/** The signed-in user, or null — the one function that turns a cookie into a person.
 * React's `cache` makes it one database read per request, however many components ask. */
export const currentUser = cache(async (): Promise<CurrentUser | null> => {
  const id = await sessionUserId();
  if (!id) return null;
  return db.user.findUnique({
    where: { id },
    select: { id: true, name: true, email: true, role: true },
  });
});

/** Every page and every action of a role starts here. Signed out: to /login. Signed in
 * as another role: to that role's home. The proxy's cookie check is only a shortcut;
 * this is the check. */
export async function requireRole(role: Role): Promise<CurrentUser> {
  const user = await currentUser();
  if (!user) redirect("/login");
  if (user.role !== role) redirect(HOME[user.role]);
  return user;
}
