"use client";

import { useState } from "react";

import { applyToJob } from "@/app/candidate/actions";

import { ActionButton } from "./action-button";
import { Icon } from "./icons";

export type Role = {
  id: string; title: string; org: string; posted: string; applied: boolean;
  must: string[]; nice: string[]; text: string | null;
};

/** Open roles with a search box and an "not applied" filter. Newest first, as listed:
 * the filter narrows by the role's own words, never by anything about the person. */
export function RoleBrowser({ roles }: { roles: Role[] }) {
  const [q, setQ] = useState("");
  const [fresh, setFresh] = useState(false);
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = roles.filter((r) => {
    if (fresh && r.applied) return false;
    const hay = [r.title, r.org, ...r.must, ...r.nice].join(" ").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="relative w-full min-w-0 sm:w-auto sm:flex-1">
          <span className="sr-only">Search roles</span>
          <Search />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by role, company or skill"
            className="h-11 w-full rounded-xl border border-line bg-panel pr-4 pl-10 text-sm outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/15" />
        </label>
        <div className="flex rounded-xl border border-line bg-panel p-1 text-sm" role="group" aria-label="Show">
          {[[false, `All (${roles.length})`], [true, `Not applied (${roles.filter((r) => !r.applied).length})`]].map(([v, label]) => (
            <button key={String(v)} type="button" onClick={() => setFresh(v as boolean)} aria-pressed={fresh === v}
              className={`rounded-lg px-3 py-1.5 font-medium transition ${fresh === v ? "bg-accent text-on-accent" : "text-muted hover:text-foreground"}`}>
              {label as string}
            </button>
          ))}
        </div>
      </div>
      {shown.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-line bg-panel px-6 py-12 text-center">
          <p className="font-medium">{roles.length ? "No roles match" : "No open roles right now"}</p>
          <p className="mt-1 text-sm text-muted">{roles.length ? "Try another word, or show all roles." : "New roles appear here as companies open them."}</p>
        </div>
      ) : (
        <ul className="space-y-4">{shown.map((r) => <RoleCard key={r.id} role={r} />)}</ul>
      )}
    </div>
  );
}

function RoleCard({ role }: { role: Role }) {
  const [open, setOpen] = useState(false);
  const long = (role.text?.length ?? 0) > 240;
  return (
    <li className="rounded-2xl border border-line bg-panel p-5 transition hover:shadow-sm sm:p-6">
      <div className="flex flex-wrap items-start gap-4">
        <span className="grid size-12 shrink-0 place-items-center rounded-xl bg-accent/10 font-semibold text-accent">
          {role.org.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-semibold leading-snug">{role.title}</h3>
          <p className="text-sm text-muted">{role.org} · posted {role.posted}</p>
        </div>
        {role.applied
          ? <span className="flex items-center gap-1.5 rounded-lg bg-ok/10 px-3 py-2 text-sm font-semibold text-ok"><Icon.Check className="size-4" /> Applied</span>
          : <ActionButton action={applyToJob.bind(null, role.id)} label="Apply" />}
      </div>

      {(role.must.length > 0 || role.nice.length > 0) && (
        <div className="mt-4 space-y-2">
          {role.must.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs font-semibold tracking-wide text-muted uppercase">Must have</span>
              {role.must.map((s) => <span key={s} className="rounded-full bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent">{s}</span>)}
            </div>
          )}
          {role.nice.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs font-semibold tracking-wide text-muted uppercase">Nice to have</span>
              {role.nice.map((s) => <span key={s} className="rounded-full px-2.5 py-1 text-xs font-medium text-muted ring-1 ring-line">{s}</span>)}
            </div>
          )}
        </div>
      )}

      {role.text && (
        <div className="mt-4 border-t border-line pt-4">
          <p className={`text-sm leading-relaxed whitespace-pre-line text-muted ${open || !long ? "" : "line-clamp-3"}`}>{role.text}</p>
          {long && (
            <button type="button" onClick={() => setOpen(!open)} className="mt-1 flex items-center gap-1 text-sm font-medium text-accent">
              {open ? "Show less" : "Read full description"} <Icon.Chevron className={`size-4 transition ${open ? "rotate-180" : ""}`} />
            </button>
          )}
        </div>
      )}
    </li>
  );
}

function Search() {
  return (
    <svg viewBox="0 0 24 24" className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" aria-hidden
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
  );
}
