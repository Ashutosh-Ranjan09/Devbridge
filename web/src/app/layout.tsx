import "./globals.css";

import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { logout } from "@/app/(auth)/actions";
import { Mark } from "@/components/icons";
import { SessionWatch } from "@/components/session-watch";
import { NavLinks } from "@/components/site-nav";
import { currentUser } from "@/lib/auth";

export const metadata: Metadata = {
  title: "DevBridge",
  description: "Developer CVs checked against evidence, skills from that evidence, and fair coding tasks.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <header className="brand-bar sticky top-0 z-40 text-white shadow-[0_1px_0_rgb(255_255_255/0.06),0_8px_24px_-12px_rgb(11_47_45/0.6)]">
          <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-6 px-4 sm:px-6">
            <Link href="/" className="flex shrink-0 items-center gap-2.5 font-semibold tracking-tight">
              <Mark className="size-7 rounded-[9px] ring-1 ring-white/25" />
              DevBridge
            </Link>
            {/* The session is read per request, so it streams in; the rest of the
                header is part of the static shell. */}
            <Suspense fallback={<span className="flex-1" />}>
              <Account />
            </Suspense>
          </div>
          <Suspense fallback={null}>
            <PhoneNav />
          </Suspense>
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
        <Link href="/login" className="ml-auto rounded-lg px-3 py-1.5 text-sm font-medium text-white/80 transition hover:bg-white/10 hover:text-white">
          Log in
        </Link>
      </>
    );
  }
  const initials = user.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <>
      <SessionWatch userId={user.id} />
      <NavLinks role={user.role} className="hidden flex-1 items-center gap-1 md:flex" />
      <div className="ml-auto flex items-center gap-1 text-sm sm:gap-2">
        <Link href="/account" className="flex items-center gap-2.5 rounded-full py-1 pr-3 pl-1 transition hover:bg-white/10" title="Your account">
          <span className="grid size-8 place-items-center rounded-full bg-white text-xs font-bold text-[#0f5752]">{initials}</span>
          <span className="hidden leading-tight lg:block">
            <span className="block font-medium">{user.name}</span>
            <span className="block text-xs text-white/60">{ROLE[user.role]}</span>
          </span>
        </Link>
        <form action={logout}>
          <button type="submit" className="rounded-lg px-3 py-1.5 text-white/70 transition hover:bg-white/10 hover:text-white">
            Log out
          </button>
        </form>
      </div>
    </>
  );
}

/** Below md the links take a row of their own, scrolling sideways if they must. */
async function PhoneNav() {
  const user = await currentUser();
  if (!user) return null;
  return <NavLinks role={user.role} className="flex gap-1 overflow-x-auto border-t border-white/10 px-4 py-2 md:hidden" />;
}

const ROLE = { CANDIDATE: "Developer", RECRUITER: "Recruiter", ADMIN: "Admin" } as const;
