import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/cookie";

/** An optimistic check only: a signed-in area without a session cookie goes straight
 * to /login. Whether the cookie is valid, and whose it is, is decided by lib/auth.ts
 * on every page and action — the docs' advice, since the proxy runs on every request. */
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  return NextResponse.redirect(new URL("/login", request.url));
}

export const config = {
  matcher: ["/candidate/:path*", "/recruiter/:path*", "/admin/:path*"],
};
