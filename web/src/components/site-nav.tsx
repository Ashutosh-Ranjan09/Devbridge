"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

import type { Role } from "@/generated/prisma/enums";

/** Each role's pages, in the header. `exact`: lit only on that path, not below it. */
const NAV: Record<Role, { href: string; label: string; exact?: boolean; not?: string }[]> = {
  CANDIDATE: [
    { href: "/candidate", label: "Home", exact: true },
    { href: "/candidate/jobs", label: "Jobs" },
    { href: "/candidate/assessments", label: "Assessments" },
    { href: "/candidate/skills", label: "My skills" },
    { href: "/candidate/cv", label: "My CV" },
  ],
  RECRUITER: [
    { href: "/recruiter", label: "Jobs", not: "/recruiter/jobs/new" },
    { href: "/recruiter/jobs/new", label: "New job" },
  ],
  ADMIN: [
    { href: "/admin", label: "System", exact: true },
    { href: "/admin/accounts", label: "Accounts" },
    { href: "/admin/candidates", label: "Candidates" },
    { href: "/admin/catalogue", label: "Checks & tasks" },
    { href: "/admin/quarantine", label: "Quarantine" },
  ],
};

/** The path is unknown while a dynamic route prerenders, so the links render unlit
 * until it is (Cache Components needs the Suspense for usePathname). */
export function NavLinks({ role, className }: { role: Role; className?: string }) {
  return (
    <Suspense fallback={<Links role={role} path={null} className={className} />}>
      <Current role={role} className={className} />
    </Suspense>
  );
}

function Current({ role, className }: { role: Role; className?: string }) {
  return <Links role={role} path={usePathname()} className={className} />;
}

function Links({ role, path, className }: { role: Role; path: string | null; className?: string }) {
  return (
    <nav className={className} aria-label="Main">
      {NAV[role].map(({ href, label, exact, not }) => {
        const on = !!path && (exact ? path === href
          : href === "/recruiter" ? (path === href || path.startsWith("/recruiter/jobs")) && !path.startsWith(not!)
          : path.startsWith(href));
        return (
          <Link key={href} href={href} aria-current={on ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium whitespace-nowrap transition ${on ? "bg-white/15 text-white" : "text-white/70 hover:bg-white/10 hover:text-white"}`}>
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
