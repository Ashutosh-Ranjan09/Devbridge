import Link from "next/link";
import type { ReactNode } from "react";

import type { ApplicationStatus, Outcome } from "@/generated/prisma/enums";

import { Icon } from "./icons";

/** The pieces the developer's pages are built from: a titled panel, an empty state,
 * a chip and a link styled as a button. */

export function Panel({ title, href, more, children }: { title: string; href?: string; more?: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="font-semibold">{title}</h2>
        {href && more && (
          <Link href={href} className="flex items-center gap-1 text-sm font-medium text-accent hover:underline">
            {more} <Icon.Arrow className="size-3.5" />
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

export function Empty({ icon, title, text, action }: { icon: keyof typeof Icon; title: string; text: string; action?: ReactNode }) {
  const Glyph = Icon[icon];
  return (
    <div className="flex flex-col items-center px-4 py-6 text-center">
      <span className="grid size-11 place-items-center rounded-full bg-background text-muted"><Glyph className="size-5" /></span>
      <p className="mt-3 font-medium">{title}</p>
      <p className="mt-1 max-w-sm text-sm text-muted">{text}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Chip({ children, tone }: { children: ReactNode; tone?: "accent" }) {
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap ${tone === "accent" ? "bg-accent/10 text-accent" : "bg-background text-muted ring-1 ring-line"}`}>
      {children}
    </span>
  );
}

export function LinkButton({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition hover:brightness-110">
      {children}
    </Link>
  );
}

const STAGES = ["Applied", "Test", "Review", "Decision"];
const STAGE_AT: Record<ApplicationStatus, number> = { APPLIED: 0, ASSESSMENT_SENT: 1, SUBMITTED: 2, DECIDED: 3 };
export const STAGE_NOW: Record<ApplicationStatus, string> = {
  APPLIED: "With the recruiter", ASSESSMENT_SENT: "Assessment sent", SUBMITTED: "Under review", DECIDED: "Decided",
};

/** Where an application is, as four steps; the current one is ringed. */
export function Stages({ status }: { status: ApplicationStatus }) {
  const at = STAGE_AT[status];
  return (
    <ol className="mt-4 grid grid-cols-4 gap-2" aria-label={`Stage: ${STAGES[at]}`}>
      {STAGES.map((label, i) => (
        <li key={label} aria-current={i === at ? "step" : undefined}>
          <span className={`block h-1.5 rounded-full ${i <= at ? "bg-accent" : "bg-line"}`} />
          {/* On a phone only the current stage is named; the bars carry the rest. */}
          <span className={`mt-1.5 truncate text-xs ${i === at ? "block font-semibold text-foreground" : `hidden sm:block ${i < at ? "text-muted" : "text-muted/70"}`}`}>
            {label}
          </span>
        </li>
      ))}
    </ol>
  );
}

const OUTCOME: Record<Outcome, { label: string; className: string }> = {
  HIRE: { label: "Offer", className: "bg-ok/10 text-ok" },
  ADVANCE: { label: "Moving forward", className: "bg-accent/10 text-accent" },
  REJECT: { label: "Not selected", className: "bg-line text-muted" },
};

export function OutcomeChip({ outcome }: { outcome: Outcome }) {
  const o = OUTCOME[outcome];
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${o.className}`}>{o.label}</span>;
}


/** A company's initials in a tile, standing in for a logo the site does not keep. */
export function OrgBadge({ name }: { name: string }) {
  const initials = name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent/10 text-sm font-semibold text-accent">{initials}</span>
  );
}
