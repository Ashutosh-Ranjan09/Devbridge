import "./globals.css";

import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { logout } from "@/app/(auth)/actions";
import { SessionWatch } from "@/components/session-watch";
import { type CurrentUser, currentUser, HOME } from "@/lib/auth";
import { messagesPath, unreadFor } from "@/lib/chat";

export const metadata: Metadata = {
  title: "DevBridge",
  description: "Developer CVs checked against evidence, skills from that evidence, and fair coding tasks.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <header className="border-b border-line bg-panel">
          <nav className="mx-auto flex w-full max-w-3xl items-center justify-between px-4 py-3">
            <Link href="/" className="font-semibold">DevBridge</Link>
            {/* The session is read per request, so it streams in; the rest of the
                header is part of the static shell. */}
            <Suspense fallback={null}>
              <Account />
            </Suspense>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}

async function Account() {
  const user = await currentUser();
  if (!user) {
    return (
      <>
        <SessionWatch userId={null} />
        <Link href="/login" className="text-sm text-accent underline">Log in</Link>
      </>
    );
  }
  return (
    <div className="flex items-center gap-4 text-sm">
      <SessionWatch userId={user.id} />
      <Link href={HOME[user.role]}>{user.name}</Link>
      <span className="text-muted">{user.role.toLowerCase()}</span>
      {user.role !== "ADMIN" && (
        <Suspense fallback={<Link href={messagesPath(user)} className="text-accent underline">Messages</Link>}>
          <MessagesLink user={user} />
        </Suspense>
      )}
      <Link href="/account" className="text-accent underline">Account</Link>
      <form action={logout}>
        <button type="submit" className="text-accent underline">Log out</button>
      </form>
    </div>
  );
}

/** Messages, with the unread count when the chat module answers. Counted when a page is
 * rendered; the chat page itself is live. */
async function MessagesLink({ user }: { user: CurrentUser }) {
  const unread = await unreadFor(user);
  return (
    <Link href={messagesPath(user)} className="text-accent underline">
      Messages{unread ? ` (${unread})` : ""}
    </Link>
  );
}
